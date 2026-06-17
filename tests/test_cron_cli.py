"""Tests for the self-management CLI (python -m d_brain.cron).

The CLI is what the brain calls via Bash, so its contract is the UX:
human-readable output, exit 0 on success, exit 2 on bad input.
"""

from datetime import UTC, datetime, timedelta

from d_brain.config import Settings
from d_brain.cron import _default_cron_dir, main
from d_brain.services.cron_store import CronStore


def _dir(tmp_path):
    return str(tmp_path / "cron")


def _future_iso():
    return (datetime.now(UTC) + timedelta(hours=2)).isoformat()


def test_add_every_writes_job_and_prints_id(tmp_path, capsys):
    rc = main(
        ["add", "--dir", _dir(tmp_path), "--prompt", "check inbox", "--every", "3600"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    jobs = CronStore(tmp_path / "cron").load()
    assert len(jobs) == 1
    assert jobs[0].prompt == "check inbox"
    assert jobs[0].state.next_run is not None
    assert jobs[0].id in out
    assert "next run" in out


def test_add_cron_with_explicit_id_and_tz(tmp_path, capsys):
    rc = main(
        [
            "add",
            "--dir",
            _dir(tmp_path),
            "--prompt",
            "morning brief",
            "--cron",
            "0 9 * * *",
            "--tz",
            "Asia/Tashkent",
            "--id",
            "morning-brief",
        ]
    )
    assert rc == 0
    jobs = CronStore(tmp_path / "cron").load()
    assert jobs[0].id == "morning-brief"
    assert jobs[0].schedule.tz == "Asia/Tashkent"
    assert "morning-brief" in capsys.readouterr().out


def test_add_oneshot_at_with_delete_after_run(tmp_path):
    rc = main(
        [
            "add",
            "--dir",
            _dir(tmp_path),
            "--prompt",
            "remind about the call",
            "--at",
            _future_iso(),
            "--delete-after-run",
        ]
    )
    assert rc == 0
    jobs = CronStore(tmp_path / "cron").load()
    assert jobs[0].delete_after_run is True
    assert jobs[0].schedule.kind == "at"


def test_add_at_in_the_past_exits_2(tmp_path, capsys):
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    rc = main(["add", "--dir", _dir(tmp_path), "--prompt", "x", "--at", past])
    assert rc == 2
    assert "past" in capsys.readouterr().err


def test_add_two_kinds_exits_2(tmp_path, capsys):
    rc = main(
        [
            "add",
            "--dir",
            _dir(tmp_path),
            "--prompt",
            "x",
            "--every",
            "60",
            "--cron",
            "0 9 * * *",
        ]
    )
    assert rc == 2
    assert capsys.readouterr().err


def test_add_duplicate_id_exits_2(tmp_path):
    args = [
        "add",
        "--dir",
        _dir(tmp_path),
        "--prompt",
        "x",
        "--every",
        "60",
        "--id",
        "dup",
    ]
    assert main(args) == 0
    assert main(args) == 2


def test_list_is_human_readable(tmp_path, capsys):
    main(
        [
            "add",
            "--dir",
            _dir(tmp_path),
            "--prompt",
            "morning brief",
            "--cron",
            "0 9 * * *",
            "--tz",
            "Asia/Tashkent",
            "--id",
            "morning-brief",
        ]
    )
    capsys.readouterr()
    rc = main(["list", "--dir", _dir(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "morning-brief" in out
    assert "0 9 * * *" in out
    assert "next" in out.lower()


def test_list_empty_store(tmp_path, capsys):
    rc = main(["list", "--dir", _dir(tmp_path)])
    assert rc == 0
    assert "no jobs" in capsys.readouterr().out.lower()


def test_remove_deletes_job(tmp_path):
    main(
        ["add", "--dir", _dir(tmp_path), "--prompt", "x", "--every", "60", "--id", "z"]
    )
    assert main(["remove", "z", "--dir", _dir(tmp_path)]) == 0
    assert CronStore(tmp_path / "cron").load() == []


def test_remove_unknown_id_exits_2(tmp_path, capsys):
    assert main(["remove", "ghost", "--dir", _dir(tmp_path)]) == 2
    assert "ghost" in capsys.readouterr().err


def test_enable_reenables_and_resets_errors(tmp_path):
    main(
        ["add", "--dir", _dir(tmp_path), "--prompt", "x", "--every", "60", "--id", "e"]
    )
    store = CronStore(tmp_path / "cron")

    def break_it(jobs):
        jobs[0].enabled = False
        jobs[0].state.consecutive_errors = 3

    store.mutate(break_it)
    assert main(["enable", "e", "--dir", _dir(tmp_path)]) == 0
    job = store.load()[0]
    assert job.enabled is True
    assert job.state.consecutive_errors == 0
    assert job.state.next_run is not None


def test_cli_and_bot_agree_on_cron_dir_under_symlinked_runtime(tmp_path, monkeypatch):
    """The CLI default cron dir MUST equal the bot's Settings.cron_dir even
    when RUNTIME_DIR contains a symlink — otherwise the brain's `cron add`
    writes jobs.json where the in-bot ticker never looks (and the two
    jobs.lock files give no mutual exclusion). Both sides resolve()."""
    real = tmp_path / "real_runtime"
    real.mkdir()
    link = tmp_path / "link_runtime"
    link.symlink_to(real)
    monkeypatch.setenv("RUNTIME_DIR", str(link))

    s = Settings(
        telegram_bot_token="t",
        deepgram_api_key="d",
        runtime_dir=str(link),
        _env_file=None,
    )
    from pathlib import Path

    assert Path(_default_cron_dir()) == s.cron_dir
