"""Liveness watchdog for the persistent Claude session.

Runs as a supervised asyncio task INSIDE the bot process (run_watchdog); the
standalone main() is kept for a separate unit if that is ever wanted again.
Each tick it decides one of:

- disk_full        → alert + STOP (a restart can't fix a full disk)
- recovered_dead   → session gone → force_recover + alert
- rate_limited     → limit hit AND the recorded window still holds → wait
- recovered_limit  → the window lapsed but the banner is still up → recover
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

import asyncio
import contextlib
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
DEFAULT_ALERT_COOLDOWN = 3600.0  # first re-alert of a persistent fault: 1h
DEFAULT_ALERT_COOLDOWN_MAX = 12 * 3600.0  # back-off cap (doubles 1h→2h→…→12h)

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
        alert_cooldown_max: float = DEFAULT_ALERT_COOLDOWN_MAX,
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
        self._alert_cooldown_max = alert_cooldown_max
        self._inflight = self.runtime_dir / "inflight"
        self._status = self.runtime_dir / "STATUS.md"
        self._last_alert_key: str | None = None
        self._last_alert_ts = 0.0
        self._alert_repeats = 0
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
        if self._last_alert_key == key:
            # Same persistent fault: back off exponentially (1h, 2h, 4h … up to
            # the cap) so an overnight outage sends a few escalating reminders
            # instead of one identical message every hour.
            cooldown = min(
                self._alert_cooldown * (2**self._alert_repeats),
                self._alert_cooldown_max,
            )
            if now - self._last_alert_ts < cooldown:
                return
            self._alert_repeats += 1
        else:
            self._alert_repeats = 0
        self._alert_fn(msg)
        self._last_alert_key = key
        self._last_alert_ts = now

    def _note_good(self) -> None:
        # Returning to a good state re-arms alerts for the next incident.
        self._last_alert_key = None
        self._alert_repeats = 0

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
            # A limit banner is only worth waiting out while the recorded
            # window still holds. Past it the banner is just old text on
            # screen — the state that used to stick forever, because this
            # branch returned early and ask() refused to type over it.
            if self.session.rate_limit_active():
                self._note_good()
                self._write_status("rate_limited")
                return "rate_limited"
            logger.info("rate-limit window lapsed with the banner still up")
            return self._recover(
                "limit", "✅ Лимит должен был обновиться — перезапустил сессию."
            )
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


async def run_watchdog(settings, bot) -> None:  # pragma: no cover - loop
    """The liveness loop as an asyncio task inside the bot process.

    One process instead of two: the tick is a handful of tmux calls every
    15s, and the ticks that can block (force_recover rebuilds a session)
    run in a worker thread so the event loop stays free. systemd's own
    WatchdogSec covers the case this loop cannot — the bot itself freezing.
    """
    from d_brain.services.runtime import get_session

    tick = settings.watchdog_tick_seconds
    pending: list[str] = []

    def alert(msg: str) -> None:
        pending.append(msg)  # queued: the loop delivers it on the event loop

    watchdog = Watchdog(
        get_session(settings),
        runtime_dir=settings.runtime_dir,
        alert_fn=alert,
        tick=tick,
    )
    logger.info("session watchdog started (tick %.0fs)", tick)
    while True:
        try:
            decision = await asyncio.to_thread(watchdog.check_once)
            if decision != "healthy":
                logger.info("watchdog: %s", decision)
        except Exception:
            logger.exception("watchdog tick failed")
        while pending:
            msg = pending.pop(0)  # pop first: an undeliverable alert must
            if settings.admin_chat_id is None:
                continue  # not queue forever and leak on a chat-less install
            with contextlib.suppress(Exception):
                await bot.send_message(settings.admin_chat_id, msg)
        await asyncio.sleep(tick)


def main() -> None:  # pragma: no cover
    """Standalone entry point — kept for `python -m d_brain.services.watchdog`
    and for running the watchdog in its own unit if ever wanted again."""
    logging.basicConfig(level=logging.INFO)
    from d_brain.config import get_settings
    from d_brain.services.runtime import get_session

    settings = get_settings()
    session = get_session(settings)
    Watchdog(
        session,
        runtime_dir=settings.runtime_dir,
        alert_fn=_telegram_alerter(settings),
        tick=settings.watchdog_tick_seconds,
    ).run()


if __name__ == "__main__":
    main()
