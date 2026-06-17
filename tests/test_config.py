"""Tests for the extended Settings (tmux-session fields)."""

from pathlib import Path

from d_brain.config import Settings


def _settings(**over):
    base = dict(telegram_bot_token="t", deepgram_api_key="d", _env_file=None)
    base.update(over)
    return Settings(**base)


def test_new_fields_have_safe_defaults():
    s = _settings()
    assert s.tz == "UTC"
    assert s.claude_model == ""  # "" → use the session's default model
    assert isinstance(s.runtime_dir, Path)


def test_admin_chat_id_is_first_allowed_user():
    s = _settings(allowed_user_ids=[111, 222])
    assert s.admin_chat_id == 111


def test_admin_chat_id_none_when_no_users():
    s = _settings(allowed_user_ids=[])
    assert s.admin_chat_id is None


def test_overrides_from_kwargs():
    s = _settings(claude_model="sonnet", tz="Asia/Tashkent")
    assert s.claude_model == "sonnet"
    assert s.tz == "Asia/Tashkent"


def test_cron_fields_have_safe_defaults():
    s = _settings()
    assert s.cron_enabled is True
    assert s.cron_tick_seconds == 60.0
    assert s.cron_job_timeout == 600.0
    assert s.cron_max_consecutive_errors == 3
    assert s.cron_retry_seconds == 300.0


def test_cron_dir_lives_under_runtime_dir():
    # Assert the invariant against the resolved runtime_dir — not a literal
    # path: the validator now resolve()s, and on macOS /tmp is a symlink to
    # /private/tmp, so a hardcoded "/tmp/rt/cron" would spuriously mismatch.
    s = _settings(runtime_dir=Path("/tmp/rt"))
    assert s.cron_dir == s.runtime_dir / "cron"


def test_tilde_paths_are_expanded():
    # pydantic-settings does not expand ~ on its own; the cron CLI does
    # expanduser — without this the bot and the CLI would silently use
    # two different state dirs.
    s = _settings(runtime_dir="~/.dbrain", vault_path="~/vault")
    assert s.runtime_dir.is_absolute()
    assert "~" not in s.runtime_dir.parts
    assert s.vault_path.is_absolute()
    assert "~" not in s.vault_path.parts


def test_relative_paths_are_resolved_absolute():
    # The default vault_path is the RELATIVE "./vault". The brain starts with
    # `cd vault && cat deploy/brain-system.md`, so a relative persona path
    # resolves against vault/ after the cd and loads NOTHING — the brain boots
    # with no persona and no reply contract. Resolving here keeps the derived
    # project_root / persona / mcp paths absolute regardless of cwd.
    s = _settings(runtime_dir="./rt", vault_path="./vault")
    assert s.runtime_dir.is_absolute()
    assert s.vault_path.is_absolute()
