"""Process-wide singletons for the shared Claude session.

The bot, the daily pipeline and the watchdog must all talk to ONE persistent
session. This module builds it lazily from Settings and hands the same
instance to every caller. An asyncio lock serializes ask() calls within the
bot process (the cross-process flock in ClaudeSession is the real mutex; this
just avoids piling up blocked worker threads).
"""

import asyncio
import uuid
from pathlib import Path

from d_brain.config import Settings
from d_brain.services.claude_session import ClaudeSession
from d_brain.services.processor import ClaudeProcessor

_session: ClaudeSession | None = None
_cron_session: ClaudeSession | None = None
_processor: ClaudeProcessor | None = None
_ask_lock = asyncio.Lock()


def reset() -> None:
    """Drop the singletons (tests only)."""
    global _session, _cron_session, _processor
    _session = None
    _cron_session = None
    _processor = None


def _persisted_name(settings: Settings) -> str:
    if settings.brain_session_name:
        return settings.brain_session_name
    # Randomize per install (fingerprint hygiene) and persist so restarts
    # reuse the same tmux session name.
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    name_file = settings.runtime_dir / "brain.name"
    if name_file.exists():
        return name_file.read_text().strip()
    name = f"dbrain_{uuid.uuid4().hex[:8]}"
    name_file.write_text(name + "\n")
    return name


def _build_session(
    settings: Settings, *, session_name: str, runtime_dir: Path
) -> ClaudeSession:
    project_root = settings.vault_path.parent
    mcp = project_root / "mcp-config.json"
    brain_prompt = project_root / "deploy" / "brain-system.md"
    # Boot assertion: without the persona file the brain would silently start
    # as a vanilla agent (no identity, no reply contract). Refuse loudly.
    if (
        not brain_prompt.exists()
        or "# second brain session contract" not in brain_prompt.read_text()
    ):
        raise RuntimeError(
            f"persona file missing or invalid: {brain_prompt} — "
            "refusing to start a personality-less brain"
        )
    return ClaudeSession(
        session_name=session_name,
        work_dir=settings.vault_path,
        runtime_dir=runtime_dir,
        mcp_config=mcp if mcp.exists() else None,
        system_prompt_file=brain_prompt,
        model=settings.claude_model or None,
    )


def get_session(settings: Settings) -> ClaudeSession:
    """Return the shared interactive ClaudeSession singleton."""
    global _session
    if _session is None:
        _session = _build_session(
            settings,
            session_name=_persisted_name(settings),
            runtime_dir=settings.runtime_dir,
        )
    return _session


def get_cron_session(settings: Settings) -> ClaudeSession:
    """Return the session scheduled jobs run in.

    By default this IS the main brain: a second always-on Claude Code process
    doubles the memory footprint of the whole install for a ticker that fires
    a handful of times a day. Jobs run as maint- turns, which the chat handler
    already recognises (is_steerable_turn) and reports as "background work"
    instead of steering user text into them.

    Set CRON_ISOLATED_SESSION=true to get the old second brain — its own tmux
    session and runtime dir, so a long job never occupies the chat.
    """
    if not settings.cron_isolated_session:
        return get_session(settings)
    global _cron_session
    if _cron_session is None:
        _cron_session = _build_session(
            settings,
            session_name=f"{_persisted_name(settings)}_cron",
            runtime_dir=settings.cron_dir,
        )
    return _cron_session


def get_processor(settings: Settings) -> ClaudeProcessor:
    global _processor
    if _processor is None:
        _processor = ClaudeProcessor(
            settings.vault_path,
            session=get_session(settings),
        )
    return _processor


def get_ask_lock() -> asyncio.Lock:
    return _ask_lock
