"""Liveness watchdog for the persistent Claude session.

Runs as its own systemd --user service in a SEPARATE slice from the session
(so an OOM kill of the brain doesn't take the watchdog with it). Each tick it
decides one of:

- disk_full        → alert + STOP (a restart can't fix a full disk)
- recovered_dead   → session gone → force_recover + alert
- rate_limited     → subscription limit hit → do NOT kill; wait it out
- logged_out       → auth lost → alert (needs re-login); do NOT kill
- recovered_hung   → wedged → force_recover + alert
- recover_deferred → wedged but a live request holds the lock → retry next tick
- healthy          → nothing to do

Hang model: hung == pane state is NOT serviceable (not READY/RATE/LOGGED_OUT)
AND no new bytes have flowed to pane.log for stall_threshold. This catches a
wedged request AND a stuck startup, never kills a long-but-live task (pane.log
keeps growing), and never kills a healthy idle READY session that merely left
an orphan inflight marker (which is cleared on READY). ask() also self-detects
stalls; the watchdog is the second line when the bot process itself died.

Alerts are debounced: a level-triggered fault (disk/logged-out) alerts once
per cooldown, and re-fires after the session returns to a good state.
"""

import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from d_brain.services.systemd_notify import notify, watchdog_interval
from d_brain.services.tmux_parse import PaneState

logger = logging.getLogger(__name__)

DEFAULT_TICK = 15.0
DEFAULT_STALL_THRESHOLD = 300.0  # 5 min stuck without visible work ⇒ wedged
DEFAULT_MIN_DISK = 500_000_000  # 500 MB
DEFAULT_ALERT_COOLDOWN = 3600.0  # re-alert a persistent fault at most hourly

_SERVICEABLE = {
    PaneState.READY,
    PaneState.RATE_LIMITED,
    PaneState.LOGGED_OUT,
}


class Watchdog:
    def __init__(
        self,
        session: Any,
        *,
        runtime_dir: Path,
        disk_free_fn: Callable[[], int] | None = None,
        clock_fn: Callable[[], float] = time.time,
        alert_fn: Callable[[str], None] = lambda _m: None,
        sleep_fn: Callable[[float], None] = time.sleep,
        tick: float = DEFAULT_TICK,
        stall_threshold: float = DEFAULT_STALL_THRESHOLD,
        min_disk_bytes: int = DEFAULT_MIN_DISK,
        alert_cooldown: float = DEFAULT_ALERT_COOLDOWN,
    ) -> None:
        self.session = session
        self.runtime_dir = Path(runtime_dir)
        self._disk_free_fn = disk_free_fn or (
            lambda: shutil.disk_usage(self.runtime_dir).free
        )
        self._clock = clock_fn
        self._alert_fn = alert_fn
        self._sleep = sleep_fn
        self._tick = tick
        self._stall_threshold = stall_threshold
        self._min_disk = min_disk_bytes
        self._alert_cooldown = alert_cooldown
        self._inflight = self.runtime_dir / "inflight"
        self._status = self.runtime_dir / "STATUS.md"
        self._last_alert_key: str | None = None
        self._last_alert_ts = 0.0
        self._stuck_since: float | None = None

    def _is_hung(self, state: PaneState) -> bool:
        # Hang model (paired with ask()'s stall detector): silence is NOT a
        # signal — a long quiet task still shows the working spinner. Hung ==
        # non-serviceable AND no visible work, PERSISTING past the threshold.
        if state in _SERVICEABLE or self.session.is_working():
            self._stuck_since = None
            return False
        now = self._clock()
        if self._stuck_since is None:
            self._stuck_since = now
            return False
        return now - self._stuck_since >= self._stall_threshold

    def _maybe_alert(self, key: str, msg: str) -> None:
        now = self._clock()
        if (
            self._last_alert_key == key
            and now - self._last_alert_ts < self._alert_cooldown
        ):
            return
        self._alert_fn(msg)
        self._last_alert_key = key
        self._last_alert_ts = now

    def _note_good(self) -> None:
        # Returning to a good state re-arms alerts for the next incident.
        self._last_alert_key = None

    def _write_status(self, state: str) -> None:
        try:
            self._status.write_text(f"state: {state}\nchecked_at: {self._clock()}\n")
        except OSError as exc:
            logger.warning("could not write STATUS.md: %s", exc)

    def _recover(self, reason: str, alert_msg: str) -> str:
        if self.session.force_recover():
            self._maybe_alert(f"recovered_{reason}", alert_msg)
            self._write_status(f"recovered_{reason}")
            return f"recovered_{reason}"
        # A live request holds the lock — don't claim a restart happened.
        self._write_status("recover_deferred")
        return "recover_deferred"

    def check_once(self) -> str:
        """One liveness tick. Returns the decision string."""
        if self._disk_free_fn() < self._min_disk:
            self._maybe_alert(
                "disk_full", "🔴 Диск переполнен — dbrain не работает (dbrain repair)."
            )
            self._write_status("disk_full")
            return "disk_full"

        if not self.session.is_healthy():
            return self._recover("dead", "♻️ Мозг был мёртв — перезапустил.")

        state = self.session.current_state()
        if state == PaneState.RATE_LIMITED:
            self._note_good()
            self._write_status("rate_limited")
            return "rate_limited"
        if state == PaneState.LOGGED_OUT:
            self._maybe_alert(
                "logged_out",
                "🔑 Claude разлогинился — нужен повторный вход (dbrain login).",
            )
            self._write_status("logged_out")
            return "logged_out"

        if self._is_hung(state):
            return self._recover("hung", "♻️ Мозг завис — перезапустил.")

        if state == PaneState.READY:
            self._inflight.unlink(missing_ok=True)  # clear any orphan marker
        self._note_good()
        self._write_status("healthy")
        return "healthy"

    def run(self) -> None:  # pragma: no cover - long-running loop
        """Main loop: tick, ping systemd watchdog, sleep."""
        notify("READY=1")
        interval = min(self._tick, watchdog_interval(self._tick))
        while True:
            try:
                self.check_once()
            except Exception:
                logger.exception("watchdog tick failed")
            notify("WATCHDOG=1")
            self._sleep(interval)


def _telegram_alerter(settings) -> Callable[[str], None]:  # pragma: no cover
    import httpx

    def send(msg: str) -> None:
        if not settings.admin_chat_id:
            return
        try:
            httpx.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                data={"chat_id": settings.admin_chat_id, "text": msg},
                timeout=10,
            )
        except Exception:
            logger.warning("watchdog alert send failed")

    return send


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    from d_brain.config import get_settings
    from d_brain.services.runtime import get_session

    settings = get_settings()
    session = get_session(settings)
    Watchdog(
        session,
        runtime_dir=settings.runtime_dir,
        alert_fn=_telegram_alerter(settings),
    ).run()


if __name__ == "__main__":
    main()
