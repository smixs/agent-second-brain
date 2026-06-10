"""Tests for the cron runner: ticker semantics, delivery, self-healing.

FakeSession pattern as in test_claude_session.py — no tmux, scripted
AskResults, recorder callables for deliver/alert, a manual clock.
"""

from datetime import UTC, datetime, timedelta

from d_brain.services.claude_session import AskResult
from d_brain.services.cron_runner import SILENT_MARKER, CronRunner, wrap_job_prompt
from d_brain.services.cron_store import CronJob, CronStore, Schedule

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


class FakeSession:
    def __init__(self, results=None, on_ask=None):
        self.results = list(results or [])
        self.on_ask = on_ask
        self.asked: list[str] = []
        self.controls: list[str] = []
        self.recovered = 0

    def ask(self, prompt, *, timeout=0.0, wrap=True):
        self.asked.append(prompt)
        if self.on_ask:
            self.on_ask()
        return self.results.pop(0) if self.results else AskResult("ok", reply="done")

    def send_control(self, text):
        self.controls.append(text)

    def force_recover(self):
        self.recovered += 1
        return True


class Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, *args):
        self.calls.append(args)


def _store(tmp_path):
    return CronStore(tmp_path / "cron")


def _add_job(store, job_id="j1", *, kind="every", next_run=NOW, **over):
    if kind == "every":
        schedule = Schedule(kind="every", every_seconds=3600)
    elif kind == "at":
        schedule = Schedule(kind="at", at=next_run.isoformat())
    else:
        schedule = Schedule(kind="cron", expr="0 9 * * *", tz="UTC")
    base = dict(id=job_id, prompt="do it", schedule=schedule)
    base.update(over)
    job = CronJob(**base)
    job.state.next_run = next_run.isoformat()
    store.mutate(lambda jobs: jobs.append(job))
    return job


def _runner(store, session, *, deliver=None, alert=None, clock=None, **over):
    base = dict(
        deliver=deliver or Recorder(),
        alert=alert or Recorder(),
        default_chat_id=111,
        job_timeout=10.0,
        max_consecutive_errors=3,
        retry_seconds=300.0,
        clock=clock or (lambda: NOW),
    )
    base.update(over)
    return CronRunner(store, session, **base)


# ── ticker semantics ─────────────────────────────────────────────────


async def test_due_job_runs_and_delivers(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "j1")
    deliver = Recorder()
    session = FakeSession([AskResult("ok", reply="<b>done</b>")])
    await _runner(store, session, deliver=deliver).tick()
    assert len(session.asked) == 1
    assert "do it" in session.asked[0]
    assert deliver.calls == [(111, "<b>done</b>")]


async def test_future_and_disabled_jobs_skipped(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "future", next_run=NOW + timedelta(hours=1))
    _add_job(store, "off", enabled=False)
    session = FakeSession()
    await _runner(store, session).tick()
    assert session.asked == []


async def test_next_run_persisted_before_ask(tmp_path):
    """At-most-once: a crash mid-ask must not refire the same slot."""
    store = _store(tmp_path)
    _add_job(store, "j1")
    seen = {}

    def snapshot():
        seen["next_run"] = store.load()[0].state.next_run

    session = FakeSession([AskResult("ok", reply="x")], on_ask=snapshot)
    await _runner(store, session).tick()
    assert seen["next_run"] == (NOW + timedelta(hours=1)).isoformat()


async def test_every_job_reschedules_after_run(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "j1")
    await _runner(store, FakeSession([AskResult("ok", reply="x")])).tick()
    job = store.load()[0]
    assert job.state.next_run == (NOW + timedelta(hours=1)).isoformat()
    assert job.state.last_status == "ok"
    assert job.state.last_run == NOW.isoformat()


async def test_hot_reload_picks_up_jobs_added_between_ticks(tmp_path):
    store = _store(tmp_path)
    session = FakeSession([AskResult("ok", reply="x")])
    runner = _runner(store, session)
    await runner.tick()
    assert session.asked == []
    _add_job(store, "late")  # e.g. brain CLI while the bot is running
    await runner.tick()
    assert len(session.asked) == 1


# ── delivery ─────────────────────────────────────────────────────────


async def test_job_chat_id_overrides_default(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "j1", chat_id=999)
    deliver = Recorder()
    await _runner(
        store, FakeSession([AskResult("ok", reply="x")]), deliver=deliver
    ).tick()
    assert deliver.calls == [(999, "x")]


async def test_silent_reply_suppresses_delivery(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "j1")
    deliver = Recorder()
    reply = f"{SILENT_MARKER} nothing new"
    await _runner(
        store, FakeSession([AskResult("ok", reply=reply)]), deliver=deliver
    ).tick()
    assert deliver.calls == []
    assert store.load()[0].state.last_status == "ok-silent"


async def test_clear_sent_after_successful_run(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "j1")
    session = FakeSession([AskResult("ok", reply="x")])
    await _runner(store, session).tick()
    assert "/clear" in session.controls


# ── one-shot lifecycle ───────────────────────────────────────────────


async def test_oneshot_deleted_after_success(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "once", kind="at", delete_after_run=True)
    await _runner(store, FakeSession([AskResult("ok", reply="x")])).tick()
    assert store.load() == []


async def test_oneshot_error_kept_with_retry(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "once", kind="at", delete_after_run=True)
    await _runner(store, FakeSession([AskResult("timeout")])).tick()
    jobs = store.load()
    assert len(jobs) == 1
    assert jobs[0].state.next_run == (NOW + timedelta(seconds=300)).isoformat()
    assert jobs[0].state.last_status == "timeout"


# ── self-healing ─────────────────────────────────────────────────────


async def test_error_recovers_session_and_counts(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "j1")
    session = FakeSession([AskResult("error", detail="boom")])
    await _runner(store, session).tick()
    assert session.recovered == 1
    job = store.load()[0]
    assert job.state.consecutive_errors == 1
    assert job.state.last_error == "boom"
    assert job.enabled is True


async def test_third_consecutive_error_disables_and_alerts(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "j1")

    def set_errors(jobs):
        jobs[0].state.consecutive_errors = 2

    store.mutate(set_errors)
    alert = Recorder()
    await _runner(store, FakeSession([AskResult("error")]), alert=alert).tick()
    job = store.load()[0]
    assert job.enabled is False
    assert job.state.consecutive_errors == 3
    assert len(alert.calls) == 1
    assert "j1" in alert.calls[0][0]


async def test_success_resets_error_counter(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "j1")

    def set_errors(jobs):
        jobs[0].state.consecutive_errors = 2

    store.mutate(set_errors)
    await _runner(store, FakeSession([AskResult("ok", reply="x")])).tick()
    assert store.load()[0].state.consecutive_errors == 0


async def test_rate_limited_skips_without_recover_or_count(tmp_path):
    """Subscription limit is not the job's fault: wait for the next slot."""
    store = _store(tmp_path)
    _add_job(store, "j1")
    session = FakeSession([AskResult("rate_limited")])
    await _runner(store, session).tick()
    job = store.load()[0]
    assert session.recovered == 0
    assert job.state.consecutive_errors == 0
    assert job.state.last_status == "rate_limited"
    assert "/clear" not in session.controls


# ── crash-safety (blind-review findings) ─────────────────────────────


async def test_at_claim_rearms_retry_instead_of_none(tmp_path):
    """A bot restart between claim and record must not brick a one-shot:
    claim leaves a retry next_run, success/record clears or deletes it."""
    store = _store(tmp_path)
    _add_job(store, "once", kind="at", delete_after_run=True)
    runner = _runner(store, FakeSession())
    claimed = runner.claim_due(NOW)
    assert len(claimed) == 1
    persisted = store.load()[0]
    assert persisted.state.next_run == (NOW + timedelta(seconds=300)).isoformat()


async def test_oneshot_success_clears_next_run_when_kept(tmp_path):
    """kind=at without delete_after_run must not refire after success."""
    store = _store(tmp_path)
    _add_job(store, "once", kind="at", delete_after_run=False)
    await _runner(store, FakeSession([AskResult("ok", reply="x")])).tick()
    job = store.load()[0]
    assert job.state.next_run is None
    assert job.state.last_status == "ok"


async def test_deliver_crash_counts_as_failure_and_clears(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "once", kind="at", delete_after_run=True)

    async def bad_deliver(*args):
        raise RuntimeError("telegram down")

    session = FakeSession([AskResult("ok", reply="x")])
    await _runner(store, session, deliver=bad_deliver).tick()
    jobs = store.load()
    assert len(jobs) == 1  # NOT deleted — will retry
    assert jobs[0].state.last_status == "deliver_error"
    assert jobs[0].state.consecutive_errors == 1
    assert "/clear" in session.controls  # context still dropped


async def test_tick_survives_job_crash_and_runs_rest_of_batch(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "boom")
    _add_job(store, "fine")

    class ExplodingRecover(FakeSession):
        def force_recover(self):
            raise RuntimeError("session not ready")

    session = ExplodingRecover(
        [AskResult("error", detail="x"), AskResult("ok", reply="y")]
    )
    deliver = Recorder()
    await _runner(store, session, deliver=deliver).tick()
    assert len(session.asked) == 2  # second job still ran
    boom = next(j for j in store.load() if j.id == "boom")
    assert boom.state.last_status == "crash"
    assert boom.state.consecutive_errors == 1


async def test_claim_skips_malformed_next_run_without_killing_tick(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "bad")
    _add_job(store, "good")

    def corrupt(jobs):
        jobs[0].state.next_run = "definitely not a date"

    store.mutate(corrupt)
    session = FakeSession([AskResult("ok", reply="x")])
    await _runner(store, session).tick()
    assert len(session.asked) == 1  # good ran, bad skipped, no exception


async def test_claim_treats_naive_next_run_as_utc(tmp_path):
    store = _store(tmp_path)
    _add_job(store, "naive")

    def make_naive(jobs):
        jobs[0].state.next_run = NOW.replace(tzinfo=None).isoformat()

    store.mutate(make_naive)
    session = FakeSession([AskResult("ok", reply="x")])
    await _runner(store, session).tick()
    assert len(session.asked) == 1


def test_load_tolerates_concurrent_rename(tmp_path):
    """FileNotFoundError between exists() and read must not escape load()."""
    from d_brain.services.cron_store import CronStore as CS

    store = CS(tmp_path / "cron")
    store.save([])
    # Simulate the race directly: file vanishes after exists() check
    store.jobs_file.unlink()
    real_exists = type(store.jobs_file).exists
    try:
        type(store.jobs_file).exists = lambda self: True  # type: ignore[method-assign]
        assert store.load() == []
    finally:
        type(store.jobs_file).exists = real_exists  # type: ignore[method-assign]


# ── prompt wrapper ───────────────────────────────────────────────────


def test_wrap_job_prompt_contract():
    wrapped = wrap_job_prompt("j1", "check the inbox", scheduled_for="2026-06-10")
    assert "[CRON JOB j1]" in wrapped
    assert "check the inbox" in wrapped
    assert "2026-06-10" in wrapped
    assert SILENT_MARKER in wrapped
    # recursion guard: a scheduled run must not breed more jobs
    assert "d_brain.cron" in wrapped
    # marker instruction belongs to ask(wrap=True), never duplicated here
    assert "<<<R:" not in wrapped
