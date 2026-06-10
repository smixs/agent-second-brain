"""Cron job store: jobs.json + schedule math. Pure file/data layer.

The file is the API between the brain and the bot: the brain (Claude Code
with Bash) edits jobs via the ``python -m d_brain.cron`` CLI, the in-bot
ticker re-reads the file every tick. All writes go through ``mutate()``
under a cross-process flock so CLI edits and runner state updates never
lose each other.
"""

import fcntl
import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from croniter import croniter

logger = logging.getLogger(__name__)

STORE_VERSION = 1


@dataclass(frozen=True)
class Schedule:
    """Union: kind='at' (one-shot ISO) | 'every' (seconds) | 'cron' (expr+tz)."""

    kind: str
    at: str | None = None
    every_seconds: int | None = None
    expr: str | None = None
    tz: str | None = None


@dataclass
class JobState:
    next_run: str | None = None  # aware ISO-8601
    last_run: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    consecutive_errors: int = 0


@dataclass
class CronJob:
    id: str
    prompt: str
    schedule: Schedule
    chat_id: int | None = None
    delete_after_run: bool = False
    enabled: bool = True
    created_at: str = ""
    state: JobState = field(default_factory=JobState)


def parse_schedule(
    *,
    at: str | None = None,
    every: int | None = None,
    cron: str | None = None,
    tz: str | None = None,
    default_tz: str,
) -> Schedule:
    """Validate flat CLI args into a Schedule. Exactly one kind required."""
    given = [v is not None for v in (at, every, cron)]
    if sum(given) != 1:
        raise ValueError("exactly one of --at / --every / --cron is required")
    if at is not None:
        parsed = datetime.fromisoformat(at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(tz or default_tz))
        return Schedule(kind="at", at=parsed.isoformat())
    if every is not None:
        if every <= 0:
            raise ValueError("--every must be a positive number of seconds")
        return Schedule(kind="every", every_seconds=every)
    assert cron is not None
    if not croniter.is_valid(cron):
        raise ValueError(f"invalid cron expression: {cron!r}")
    zone = tz or default_tz
    ZoneInfo(zone)  # raises on unknown zone
    return Schedule(kind="cron", expr=cron, tz=zone)


def compute_next_run(schedule: Schedule, *, now: datetime) -> datetime | None:
    """Next fire time. Anchored to ``now`` — missed slots are not replayed
    (misfire policy: at most one catch-up, the caller fires due jobs once)."""
    if schedule.kind == "at":
        assert schedule.at is not None
        return datetime.fromisoformat(schedule.at)
    if schedule.kind == "every":
        assert schedule.every_seconds is not None
        return now + timedelta(seconds=schedule.every_seconds)
    if schedule.kind == "cron":
        assert schedule.expr is not None
        local_now = now.astimezone(ZoneInfo(schedule.tz or "UTC"))
        nxt: datetime = croniter(schedule.expr, local_now).get_next(datetime)
        return nxt
    raise ValueError(f"unknown schedule kind: {schedule.kind!r}")


def _job_from_dict(raw: dict) -> CronJob:
    sched = raw.get("schedule") or {}
    state = raw.get("state") or {}
    return CronJob(
        id=raw["id"],
        prompt=raw["prompt"],
        schedule=Schedule(
            kind=sched.get("kind", ""),
            at=sched.get("at"),
            every_seconds=sched.get("every_seconds"),
            expr=sched.get("expr"),
            tz=sched.get("tz"),
        ),
        chat_id=raw.get("chat_id"),
        delete_after_run=raw.get("delete_after_run", False),
        enabled=raw.get("enabled", True),
        created_at=raw.get("created_at", ""),
        state=JobState(
            next_run=state.get("next_run"),
            last_run=state.get("last_run"),
            last_status=state.get("last_status"),
            last_error=state.get("last_error"),
            consecutive_errors=state.get("consecutive_errors", 0),
        ),
    )


class CronStore:
    """jobs.json with atomic writes and a cross-process write lock."""

    def __init__(self, cron_dir: Path) -> None:
        self.cron_dir = Path(cron_dir)
        self.jobs_file = self.cron_dir / "jobs.json"
        self.lock_file = self.cron_dir / "jobs.lock"

    def load(self) -> list[CronJob]:
        if not self.jobs_file.exists():
            return []
        try:
            raw = json.loads(self.jobs_file.read_text())
            return [_job_from_dict(j) for j in raw.get("jobs", [])]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            # Keep the evidence, never wipe it: rename and start empty.
            quarantine = self.jobs_file.with_name(
                f"jobs.json.corrupt-{int(time.time())}"
            )
            self.jobs_file.rename(quarantine)
            logger.error("corrupt jobs.json moved to %s: %s", quarantine, exc)
            return []

    def save(self, jobs: list[CronJob]) -> None:
        self.cron_dir.mkdir(parents=True, exist_ok=True)
        payload = {"version": STORE_VERSION, "jobs": [asdict(j) for j in jobs]}
        tmp = self.jobs_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        os.replace(tmp, self.jobs_file)

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.cron_dir.mkdir(parents=True, exist_ok=True)
        with open(self.lock_file, "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def mutate(self, fn: Callable[[list[CronJob]], None]) -> list[CronJob]:
        """Read-modify-write under the lock — the only write path for both
        the CLI and the runner, so concurrent edits never get lost."""
        with self.locked():
            jobs = self.load()
            fn(jobs)
            self.save(jobs)
            return jobs
