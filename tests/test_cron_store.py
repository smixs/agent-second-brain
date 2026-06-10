"""Tests for the cron job store and schedule math (pure, no tmux)."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from d_brain.services.cron_store import (
    CronJob,
    CronStore,
    Schedule,
    compute_next_run,
    parse_schedule,
)

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)  # 17:00 in Tashkent


# ── parse_schedule ───────────────────────────────────────────────────


def test_parse_requires_exactly_one_kind():
    with pytest.raises(ValueError):
        parse_schedule(default_tz="UTC")
    with pytest.raises(ValueError):
        parse_schedule(at="2026-06-12T18:00:00+05:00", every=60, default_tz="UTC")


def test_parse_rejects_invalid_cron_expr():
    with pytest.raises(ValueError):
        parse_schedule(cron="not a cron", default_tz="UTC")


def test_parse_cron_defaults_tz():
    s = parse_schedule(cron="0 9 * * *", default_tz="Asia/Tashkent")
    assert s.kind == "cron"
    assert s.expr == "0 9 * * *"
    assert s.tz == "Asia/Tashkent"


def test_parse_naive_at_gets_default_tz():
    s = parse_schedule(at="2026-06-12T18:00:00", default_tz="Asia/Tashkent")
    assert s.kind == "at"
    parsed = datetime.fromisoformat(s.at)
    assert parsed.utcoffset() == timedelta(hours=5)


def test_parse_every_keeps_seconds():
    s = parse_schedule(every=3600, default_tz="UTC")
    assert s.kind == "every"
    assert s.every_seconds == 3600


def test_parse_rejects_nonpositive_every():
    with pytest.raises(ValueError):
        parse_schedule(every=0, default_tz="UTC")


# ── compute_next_run ─────────────────────────────────────────────────


def test_next_run_at_is_the_at_time_independent_of_now():
    s = Schedule(kind="at", at="2026-06-12T18:00:00+05:00")
    assert compute_next_run(s, now=NOW) == datetime.fromisoformat(
        "2026-06-12T18:00:00+05:00"
    )


def test_next_run_every_anchors_to_now_not_missed_slots():
    # Misfire policy: after downtime the next run is now+interval, no backlog.
    s = Schedule(kind="every", every_seconds=3600)
    assert compute_next_run(s, now=NOW) == NOW + timedelta(hours=1)


def test_next_run_cron_respects_tz():
    s = Schedule(kind="cron", expr="0 9 * * *", tz="Asia/Tashkent")
    nxt = compute_next_run(s, now=NOW)
    # 17:00 local → next 09:00 local is tomorrow
    assert nxt == datetime(2026, 6, 11, 9, 0, tzinfo=ZoneInfo("Asia/Tashkent"))


def test_next_run_cron_same_day_when_still_ahead():
    early = datetime(2026, 6, 10, 2, 0, tzinfo=timezone.utc)  # 07:00 local
    s = Schedule(kind="cron", expr="0 9 * * *", tz="Asia/Tashkent")
    nxt = compute_next_run(s, now=early)
    assert nxt == datetime(2026, 6, 10, 9, 0, tzinfo=ZoneInfo("Asia/Tashkent"))


# ── store ────────────────────────────────────────────────────────────


def _job(job_id="j1", **over):
    base = dict(
        id=job_id,
        prompt="do the thing",
        schedule=Schedule(kind="every", every_seconds=60),
    )
    base.update(over)
    return CronJob(**base)


def test_load_missing_file_returns_empty(tmp_path):
    assert CronStore(tmp_path / "cron").load() == []


def test_save_load_roundtrip(tmp_path):
    store = CronStore(tmp_path / "cron")
    job = _job()
    job.state.next_run = "2026-06-10T13:00:00+00:00"
    store.save([job])
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].id == "j1"
    assert loaded[0].schedule.every_seconds == 60
    assert loaded[0].state.next_run == "2026-06-10T13:00:00+00:00"
    assert loaded[0].enabled is True


def test_save_is_atomic_no_tmp_left(tmp_path):
    store = CronStore(tmp_path / "cron")
    store.save([_job()])
    leftovers = [p for p in (tmp_path / "cron").iterdir() if "tmp" in p.name]
    assert leftovers == []


def test_corrupt_file_is_renamed_and_load_returns_empty(tmp_path):
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir(parents=True)
    (cron_dir / "jobs.json").write_text("{not json")
    store = CronStore(cron_dir)
    assert store.load() == []
    corrupted = list(cron_dir.glob("jobs.json.corrupt-*"))
    assert len(corrupted) == 1
    assert not (cron_dir / "jobs.json").exists()


def test_mutate_persists_changes_under_lock(tmp_path):
    store = CronStore(tmp_path / "cron")
    store.save([_job("a"), _job("b")])

    def disable_b(jobs):
        for j in jobs:
            if j.id == "b":
                j.enabled = False

    result = store.mutate(disable_b)
    assert [j.enabled for j in result] == [True, False]
    assert [j.enabled for j in store.load()] == [True, False]


def test_unknown_fields_in_file_are_ignored(tmp_path):
    # Forward compatibility: a newer writer must not crash an older reader.
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir(parents=True)
    payload = {
        "version": 1,
        "jobs": [
            {
                "id": "x",
                "prompt": "p",
                "schedule": {"kind": "every", "every_seconds": 5, "novel": 1},
                "state": {"consecutive_errors": 0, "novel": 2},
                "novel": 3,
            }
        ],
    }
    (cron_dir / "jobs.json").write_text(json.dumps(payload))
    jobs = CronStore(cron_dir).load()
    assert jobs[0].id == "x"
