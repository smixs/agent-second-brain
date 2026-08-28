"""Durable rate-limit state with an EXPIRY — the cure for the sticky banner.

The pane text is the only source of the limit signal, and the banner stays
on screen long after the limit resets. ask() used to short-circuit on that
text *before typing anything*, so the banner could never be pushed off
screen: a self-locking loop that only a manual `tmux kill-session` broke.

Here the signal gets a lifetime. When a limit is observed we parse the reset
moment out of the banner ("resets at 3pm", "resets in 42 minutes") and
persist {hit_at, until, detail} next to the pane lock. While `until` is in
the future, callers answer "rate limited" without touching tmux at all
(cheap). Once it passes, the state is stale BY DEFINITION and the next
ask() must PROBE: wipe the pane and send a real prompt — the only
trustworthy test of whether the limit is gone.

The file is shared by the bot, the cron ticker and the watchdog, so all
three agree on when the brain may try again. A missing/corrupt file simply
means "no known limit" — never an error.
"""

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# No parseable reset time in the banner → assume this long. Short enough to
# recover the same hour, long enough not to burn turns against a live limit.
DEFAULT_COOLDOWN = 1800.0  # 30 min
# Hard cap on any parsed window. A weekly limit can be days away, but probing
# once every few hours costs one prompt and guarantees the state can never
# strand the brain because of a misparse.
MAX_COOLDOWN = 6 * 3600.0

# "resets at 3pm" / "reset at 15:00" / "resets 3:30 PM" / "will reset at 9am"
_CLOCK_RE = re.compile(
    r"reset[sz]?\b(?:\s+(?:at|on))?\s+"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)?",
    re.I,
)
# "resets in 42 minutes" / "try again in 2 hours"
_IN_RE = re.compile(
    r"(?:reset[sz]?|try again|available again)\s+in\s+"
    r"(?P<n>\d+)\s*(?P<unit>second|sec|minute|min|hour|hr)s?",
    re.I,
)
_UNIT_SECONDS = {
    "second": 1, "sec": 1,
    "minute": 60, "min": 60,
    "hour": 3600, "hr": 3600,
}


def _now_local() -> datetime:
    return datetime.now().astimezone()


def parse_reset_time(text: str, now: datetime) -> datetime | None:
    """Best-effort reset moment from a limit banner, or None.

    Understands a wall-clock ("resets at 3pm" — the next occurrence of that
    time) and a relative window ("resets in 42 minutes"). Any timezone the
    banner names is ignored: the brain and the bot share a machine, so local
    time is the right frame. The result is never in the past and never
    further out than MAX_COOLDOWN.
    """
    if not text:
        return None

    m = _IN_RE.search(text)
    if m:
        seconds = int(m.group("n")) * _UNIT_SECONDS[m.group("unit").lower()]
        return _clamp(now + timedelta(seconds=seconds), now)

    m = _CLOCK_RE.search(text)
    if not m:
        return None
    hour = int(m.group("h"))
    minute = int(m.group("m") or 0)
    ampm = (m.group("ampm") or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return _clamp(target, now)


def _clamp(target: datetime, now: datetime) -> datetime:
    ceiling = now + timedelta(seconds=MAX_COOLDOWN)
    return min(target, ceiling)


@dataclass(frozen=True)
class RateLimitRecord:
    """A limit we have observed and when we may try again."""

    hit_at: datetime
    until: datetime
    detail: str = ""

    def expired(self, now: datetime) -> bool:
        return now >= self.until


class RateLimitState:
    """The {hit_at, until, detail} record on disk. Never raises."""

    def __init__(
        self,
        path: Path | str,
        *,
        now_fn: Callable[[], datetime] = _now_local,
        default_cooldown: float = DEFAULT_COOLDOWN,
    ) -> None:
        self.path = Path(path)
        self._now = now_fn
        self._default_cooldown = default_cooldown

    def read(self) -> RateLimitRecord | None:
        """The stored record, or None when there is no usable one."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return RateLimitRecord(
                hit_at=datetime.fromisoformat(raw["hit_at"]),
                until=datetime.fromisoformat(raw["until"]),
                detail=str(raw.get("detail", "")),
            )
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # A corrupt file must never brick the brain: drop it and move on.
            logger.warning("unreadable rate-limit state %s: %s", self.path, exc)
            self.clear()
            return None

    def status(self) -> tuple[RateLimitRecord | None, bool]:
        """``(record, still_holding)``.

        Three outcomes the callers care about: ``(None, False)`` — no known
        limit, proceed; ``(rec, True)`` — wait, don't touch the pane;
        ``(rec, False)`` — the window lapsed, so whatever the pane shows is
        stale and the caller must PROBE with a real prompt.
        """
        rec = self.read()
        if rec is None:
            return None, False
        return rec, not rec.expired(self._now())

    def active(self) -> bool:
        """True while the observed limit is still expected to hold."""
        return self.status()[1]

    def record(self, banner: str = "") -> RateLimitRecord:
        """Persist a freshly observed limit, dating it from the banner."""
        now = self._now()
        until = parse_reset_time(banner, now) or (
            now + timedelta(seconds=self._default_cooldown)
        )
        rec = RateLimitRecord(hit_at=now, until=until, detail=banner.strip()[:300])
        self._write(rec)
        logger.warning(
            "rate limit recorded, next attempt after %s (%s)",
            rec.until.isoformat(timespec="seconds"),
            rec.detail or "no reset time in banner",
        )
        return rec

    def clear(self) -> None:
        """Forget the limit — on a successful turn, a recovery or /reset."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not clear rate-limit state: %s", exc)

    def _write(self, rec: RateLimitRecord) -> None:
        payload = json.dumps(
            {
                "hit_at": rec.hit_at.isoformat(),
                "until": rec.until.isoformat(),
                "detail": rec.detail,
            },
            ensure_ascii=False,
        )
        tmp = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(payload + "\n", encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)  # atomic: readers see old or new, never half
        except OSError as exc:
            logger.warning("could not persist rate-limit state: %s", exc)
