"""Tests for the shared session/processor singletons."""

import d_brain.services.runtime as rt
from d_brain.config import Settings


def _settings(tmp_path, *, persona: bool = True, **over):
    base = dict(
        telegram_bot_token="t",
        deepgram_api_key="d",
        vault_path=tmp_path / "vault",
        runtime_dir=tmp_path / "rt",
        _env_file=None,
    )
    base.update(over)
    if persona:  # the boot assertion requires the persona file
        deploy = tmp_path / "deploy"
        deploy.mkdir(parents=True, exist_ok=True)
        (deploy / "brain-system.md").write_text("# d-brain session contract\n")
    return Settings(**base)


def test_get_session_is_singleton(tmp_path):
    rt.reset()
    s = _settings(tmp_path)
    assert rt.get_session(s) is rt.get_session(s)


def test_get_processor_is_singleton_and_wired_to_session(tmp_path):
    rt.reset()
    s = _settings(tmp_path)
    p = rt.get_processor(s)
    assert rt.get_processor(s) is p
    assert p.session is rt.get_session(s)


def test_session_name_persisted_and_stable(tmp_path):
    rt.reset()
    s = _settings(tmp_path)
    name1 = rt.get_session(s).session_name
    rt.reset()  # drop in-memory singleton; must re-read persisted name
    name2 = rt.get_session(s).session_name
    assert name1 == name2
    assert name1.startswith("dbrain")


def test_explicit_session_name_used(tmp_path):
    rt.reset()
    s = _settings(tmp_path, brain_session_name="dbrain_fixed")
    assert rt.get_session(s).session_name == "dbrain_fixed"


def test_get_cron_session_is_isolated_sibling(tmp_path):
    """The cron brain is a SECOND ClaudeSession: same persona and vault,
    but its own tmux session name and its own runtime dir, so pane.lock /
    pane.log / ready never collide with the main brain's."""
    rt.reset()
    s = _settings(tmp_path)
    main = rt.get_session(s)
    cron = rt.get_cron_session(s)
    assert cron is not main
    assert cron.session_name == f"{main.session_name}_cron"
    assert cron.runtime_dir == s.cron_dir
    assert cron.runtime_dir != main.runtime_dir
    assert cron.work_dir == main.work_dir


def test_get_cron_session_is_singleton_and_reset_clears(tmp_path):
    rt.reset()
    s = _settings(tmp_path)
    c1 = rt.get_cron_session(s)
    assert rt.get_cron_session(s) is c1
    rt.reset()
    assert rt.get_cron_session(s) is not c1


def test_get_cron_session_refuses_without_persona(tmp_path):
    import pytest

    rt.reset()
    s = _settings(tmp_path, persona=False)
    with pytest.raises(RuntimeError, match="persona"):
        rt.get_cron_session(s)


def test_relative_vault_path_yields_absolute_brain_paths(tmp_path, monkeypatch):
    """A fork installed with the default relative VAULT_PATH=./vault must
    still get ABSOLUTE paths into the start command. The brain runs
    `cd vault && cat deploy/brain-system.md`: a relative persona path would
    resolve against vault/ AFTER the cd and load nothing — silently booting a
    personality-less agent (the boot assertion passes because it reads from
    the bot's cwd, not the brain's). Resolving vault_path at config time keeps
    project_root / persona / mcp absolute regardless of the brain's cwd."""
    rt.reset()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "brain-system.md").write_text("# d-brain session contract\n")
    s = Settings(
        telegram_bot_token="t",
        deepgram_api_key="d",
        vault_path="./vault",
        runtime_dir="./rt",
        _env_file=None,
    )
    sess = rt.get_session(s)
    assert sess.system_prompt_file is not None
    assert sess.system_prompt_file.is_absolute()
    assert sess.work_dir.is_absolute()


def test_get_session_refuses_without_persona(tmp_path):
    """runtime.py used to silently pass system_prompt_file=None when the
    persona file is missing — booting a personality-less vanilla agent.
    v3.0: refuse loudly instead."""
    import pytest

    rt.reset()
    s = _settings(tmp_path, persona=False)
    with pytest.raises(RuntimeError, match="persona"):
        rt.get_session(s)
