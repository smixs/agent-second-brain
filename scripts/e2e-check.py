#!/usr/bin/env python
"""Smoke test: bring up an ad-hoc interactive session and verify it answers.

Does NOT touch the running bot or its tmux session (uses a throwaway session
name + runtime dir). Verifies the whole interactive path works on this host:
session start, trust handling, login, marker extraction.

    uv run python scripts/e2e-check.py [vault_path]

Exit 0 if the session replied PONG, 1 otherwise.
"""

import shutil
import sys
import tempfile
from pathlib import Path

from d_brain.services.claude_session import ClaudeSession

vault = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("vault")
runtime = Path(tempfile.mkdtemp(prefix="dbrain_e2e_"))
session = ClaudeSession(
    "dbrain_e2e_smoke",
    vault,
    runtime,
    startup_timeout=90,
    stall_timeout=90,
    poll_interval=2.0,
)
try:
    res = session.ask("Reply with exactly the word PONG.", timeout=120)
    print(f"status={res.status} reply={res.reply!r} detail={res.detail}")
    ok = res.ok and bool(res.reply) and "PONG" in (res.reply or "")
    sys.exit(0 if ok else 1)
finally:
    session.kill()
    shutil.rmtree(runtime, ignore_errors=True)
