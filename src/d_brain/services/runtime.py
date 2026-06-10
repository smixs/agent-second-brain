"""Process-wide singletons for the shared Claude session.

The bot, the daily pipeline and the watchdog must all talk to ONE persistent
session. This module builds it lazily from Settings and hands the same
instance to every caller. An asyncio lock serializes ask() calls within the
bot process (the cross-process flock in ClaudeSession is the real mutex; this
just avoids piling up blocked worker threads).
"""

import asyncio
import uuid

from d_brain.config import Settings
from d_brain.services.claude_session import ClaudeSession
from d_brain.services.processor import ClaudeProcessor

_session: ClaudeSession | None = None
_processor: ClaudeProcessor | None = None
_ask_lock = asyncio.Lock()


def reset() -> None:
    """Drop the singletons (tests only)."""
    global _session, _processor
    _session = None
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


def get_session(settings: Settings) -> ClaudeSession:
    """Return the shared interactive ClaudeSession singleton."""
    global _session
    if _session is not None:
        return _session
    project_root = settings.vault_path.parent
    mcp = project_root / "mcp-config.json"
    brain_prompt = project_root / "deploy" / "brain-system.md"
    # Boot assertion: without the persona file the brain would silently start
    # as a vanilla agent (no identity, no reply contract). Refuse loudly.
    if (
        not brain_prompt.exists()
        or "# d-brain session contract" not in brain_prompt.read_text()
    ):
        raise RuntimeError(
            f"persona file missing or invalid: {brain_prompt} — "
            "refusing to start a personality-less brain"
        )
    _session = ClaudeSession(
        session_name=_persisted_name(settings),
        work_dir=settings.vault_path,
        runtime_dir=settings.runtime_dir,
        mcp_config=mcp if mcp.exists() else None,
        system_prompt_file=brain_prompt,
        model=settings.claude_model or None,
    )
    return _session


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
