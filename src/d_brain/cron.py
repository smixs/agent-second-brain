"""Self-management CLI for cron jobs: ``python -m d_brain.cron``.

This is the brain's interface to its own schedule — the brain (a Claude
Code session with Bash) calls it; the in-bot ticker picks the file up on
the next tick. Standalone on purpose: it must run without the bot's
required env (tokens), so it never imports Settings. Defaults follow the
same env vars Settings reads (RUNTIME_DIR, TZ).
"""

import argparse
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from d_brain.services.cron_store import (
    CronJob,
    CronStore,
    compute_next_run,
    parse_schedule,
)


def _default_cron_dir() -> str:
    # Mirror Settings._expand_user EXACTLY (expanduser + resolve): the bot
    # ticker reads the resolved dir, so a bare expanduser here would split the
    # CLI's jobs.json from the ticker's under any symlinked runtime path
    # (container bind-mount, NFS home, /home → /srv/home).
    runtime = Path(os.environ.get("RUNTIME_DIR", "~/.dbrain")).expanduser().resolve()
    return str(runtime / "cron")


def _default_tz() -> str:
    return os.environ.get("TZ") or "UTC"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m d_brain.cron",
        description="Manage d-brain scheduled jobs (jobs.json)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_dir(p: argparse.ArgumentParser) -> None:
        p.add_argument("--dir", default=_default_cron_dir(), help="cron state dir")

    p_add = sub.add_parser("add", help="add a job")
    add_dir(p_add)
    p_add.add_argument("--prompt", required=True, help="instruction for the run")
    p_add.add_argument("--at", help="one-shot ISO datetime")
    p_add.add_argument("--every", type=int, help="interval in seconds")
    p_add.add_argument("--cron", help="5-field cron expression")
    p_add.add_argument("--tz", default=_default_tz(), help="IANA timezone")
    p_add.add_argument("--id", dest="job_id", help="job id (default: generated)")
    p_add.add_argument("--chat-id", type=int, help="Telegram chat for delivery")
    p_add.add_argument("--delete-after-run", action="store_true")

    p_list = sub.add_parser("list", help="list jobs")
    add_dir(p_list)

    p_remove = sub.add_parser("remove", help="remove a job")
    p_remove.add_argument("job_id")
    add_dir(p_remove)

    p_enable = sub.add_parser("enable", help="re-enable an auto-disabled job")
    p_enable.add_argument("job_id")
    add_dir(p_enable)

    return parser


def _fmt_schedule(job: CronJob) -> str:
    s = job.schedule
    if s.kind == "at":
        return f"at {s.at}"
    if s.kind == "every":
        return f"every {s.every_seconds}s"
    return f"cron '{s.expr}' ({s.tz})"


def _cmd_add(args: argparse.Namespace) -> int:
    store = CronStore(Path(args.dir))
    now = datetime.now(UTC)
    schedule = parse_schedule(
        at=args.at, every=args.every, cron=args.cron, tz=args.tz, default_tz=args.tz
    )
    next_run = compute_next_run(schedule, now=now)
    if schedule.kind == "at" and next_run is not None and next_run <= now:
        raise ValueError(f"--at {args.at} is in the past")
    job = CronJob(
        id=args.job_id or f"{schedule.kind}-{uuid.uuid4().hex[:6]}",
        prompt=args.prompt,
        schedule=schedule,
        chat_id=args.chat_id,
        delete_after_run=args.delete_after_run,
        created_at=now.isoformat(),
    )
    job.state.next_run = next_run.isoformat() if next_run else None

    def insert(jobs: list[CronJob]) -> None:
        if any(j.id == job.id for j in jobs):
            raise ValueError(f"job id already exists: {job.id}")
        jobs.append(job)

    store.mutate(insert)
    print(f"added {job.id} ({_fmt_schedule(job)}); next run {job.state.next_run}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    jobs = CronStore(Path(args.dir)).load()
    if not jobs:
        print("no jobs")
        return 0
    for j in jobs:
        flags = "" if j.enabled else " [disabled]"
        oneshot = " [one-shot]" if j.delete_after_run else ""
        print(
            f"{j.id}: {_fmt_schedule(j)}{oneshot}{flags}\n"
            f"  next: {j.state.next_run}  last: {j.state.last_run or '-'} "
            f"({j.state.last_status or '-'})\n"
            f"  prompt: {j.prompt}"
        )
    return 0


def _find(jobs: list[CronJob], job_id: str) -> CronJob:
    for j in jobs:
        if j.id == job_id:
            return j
    raise ValueError(f"no such job: {job_id}")


def _cmd_remove(args: argparse.Namespace) -> int:
    store = CronStore(Path(args.dir))

    def drop(jobs: list[CronJob]) -> None:
        jobs.remove(_find(jobs, args.job_id))

    store.mutate(drop)
    print(f"removed {args.job_id}")
    return 0


def _cmd_enable(args: argparse.Namespace) -> int:
    store = CronStore(Path(args.dir))
    now = datetime.now(UTC)

    def fix(jobs: list[CronJob]) -> None:
        job = _find(jobs, args.job_id)
        job.enabled = True
        job.state.consecutive_errors = 0
        nxt = compute_next_run(job.schedule, now=now)
        job.state.next_run = nxt.isoformat() if nxt else None

    store.mutate(fix)
    print(f"enabled {args.job_id}")
    return 0


_COMMANDS = {
    "add": _cmd_add,
    "list": _cmd_list,
    "remove": _cmd_remove,
    "enable": _cmd_enable,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
