"""Drive a persistent INTERACTIVE Claude Code session inside a tmux pane.

This is the core of the post-2026-06-15 design: instead of spawning
`claude -p` per request (which moves to a paid Agent SDK credit), we keep
one long-lived interactive `claude` alive in tmux and "type" prompts into
it. Interactive usage stays on the subscription.

All access to the pane goes through a single cross-process file lock
(`pane.lock`) so the bot, the daily pipeline and the watchdog never talk to
the pane at once. The watchdog recovers a wedged session via
``force_recover()`` (non-blocking lock), and ``ask()`` self-detects a stall
(no visible turn — the working spinner gone without completion) so it
releases the lock quickly instead of holding it for the full timeout.
Silence is NOT a hang signal: a long quiet task still shows the spinner.

Pure text parsing lives in tmux_parse; this module only orchestrates tmux
and timing, so it is tested with a fake runner + injected clock/sleep/rid.

NOTE: runtime_dir must be on a LOCAL filesystem — fcntl.flock is unreliable
on NFS/9p and would silently degrade to no serialization.
"""

import fcntl
import logging
import os
import shlex
import subprocess
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from d_brain.services.tmux_parse import (
    PaneState,
    classify_state,
    extract_reply,
    has_survey_prompt,
    is_complete,
    is_idle,
    is_working,
    strip_chrome,
)

logger = logging.getLogger(__name__)

Runner = Callable[..., subprocess.CompletedProcess]

DEFAULT_TIMEOUT = 1200  # 20 min, matches the old subprocess pipeline
DEFAULT_STALL_TIMEOUT = 180  # no new pane bytes for this long ⇒ wedged
# request_id prefix that marks a turn as maintenance (pipeline, doctor,
# /process) — such turns are never steering targets for chat input.
MAINT_PREFIX = "maint-"
_PANE_WIDTH = "200"
# Height 50 (not taller): the TUI draws its footer (idle ❯ / bypass line)
# just below content, so on a tall pane the footer lands mid-screen with a
# blank bottom — and chrome-region state detection misses it. At 50 the
# footer sits near the bottom. Long replies are still captured via scrollback.
_PANE_HEIGHT = "50"
# Scrollback lines to capture. NOTE (verified live on tmux 3.6b): `-S -` and
# large counts like `-S -2000` return EMPTY on this TUI; a modest concrete
# count works and includes scrollback (pane history ~2000 lines).
_CAPTURE_SCROLLBACK = "-200"


@dataclass
class AskResult:
    """Outcome of a single ask() round."""

    status: str  # "ok" | "rate_limited" | "logged_out" | "timeout" | "error"
    reply: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class ClaudeSession:
    """A single interactive Claude Code session in a named tmux session."""

    def __init__(
        self,
        session_name: str,
        work_dir: Path,
        runtime_dir: Path,
        *,
        mcp_config: Path | None = None,
        system_prompt_file: Path | None = None,
        model: str | None = None,
        claude_bin: str = "claude",
        runner: Runner = subprocess.run,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
        rid_factory: Callable[[], str] | None = None,
        poll_interval: float = 1.0,
        paste_settle: float = 0.3,
        startup_timeout: float = 90.0,
        stall_timeout: float = DEFAULT_STALL_TIMEOUT,
    ) -> None:
        self.session_name = session_name
        self.work_dir = Path(work_dir)
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        # The dir holds the full pane transcript and turn state — owner-only,
        # enforced on every start so pre-existing installs get repaired too.
        # A foreign-owned dir (e.g. once created via sudo) must degrade to a
        # loud warning, not a constructor crash-loop across all services.
        try:
            os.chmod(self.runtime_dir, 0o700)
        except OSError as exc:
            logger.warning(
                "could not restrict %s to owner-only: %s", self.runtime_dir, exc
            )
        self.mcp_config = Path(mcp_config) if mcp_config else None
        self.system_prompt_file = (
            Path(system_prompt_file) if system_prompt_file else None
        )
        self.model = model
        self.claude_bin = claude_bin
        self._runner = runner
        self._sleep = sleep_fn
        self._clock = clock_fn
        self._rid_factory = rid_factory or (lambda: uuid.uuid4().hex[:8])
        self._poll_interval = poll_interval
        self._paste_settle = paste_settle
        self._startup_timeout = startup_timeout
        self._stall_timeout = stall_timeout

        # Address the session's active window/pane by name. A fixed ":0.0"
        # breaks under `base-index 1` (window 0 won't exist) → empty capture.
        self._target = session_name
        self._pane_log = self.runtime_dir / "pane.log"
        self._ready_flag = self.runtime_dir / "ready"
        self._inflight = self.runtime_dir / "inflight"
        self._pane_lock = self.runtime_dir / "pane.lock"

    # ── tmux helpers ─────────────────────────────────────────────────

    def _tmux(
        self, *args: str, input_text: str | None = None
    ) -> subprocess.CompletedProcess:
        proc = self._runner(
            ["tmux", *args],
            capture_output=True,
            text=True,
            check=False,
            input=input_text,
        )
        if proc.returncode != 0:
            logger.warning(
                "tmux %s failed (rc=%s): %s",
                args[0],
                proc.returncode,
                (proc.stderr or "").strip(),
            )
        return proc

    def _capture(self) -> str:
        return self._tmux(
            "capture-pane", "-t", self._target, "-p", "-S", _CAPTURE_SCROLLBACK
        ).stdout

    def _pane_log_size(self) -> int:
        """Byte size of the piped transcript — a growing log is the
        version-proof liveness signal (no on-screen text dependency)."""
        try:
            return self._pane_log.stat().st_size
        except OSError:
            return 0

    def _session_exists(self) -> bool:
        return self._tmux("has-session", "-t", self.session_name).returncode == 0

    def _send_enter(self) -> None:
        self._tmux("send-keys", "-t", self._target, "Enter")

    def _interrupt(self) -> None:
        self._tmux("send-keys", "-t", self._target, "C-c")

    # ── file lock (single lock; see module docstring) ────────────────

    @contextmanager
    def _locked(self, *, blocking: bool = True):
        fd = os.open(self._pane_lock, os.O_CREAT | os.O_RDWR, 0o644)
        acquired = False
        try:
            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(fd, flags)
            acquired = True
            yield True
        except BlockingIOError:
            yield False
        finally:
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    # ── lifecycle ────────────────────────────────────────────────────

    def _start_command(self) -> str:
        parts = [shlex.quote(self.claude_bin), "--dangerously-skip-permissions"]
        if self.mcp_config:
            parts += ["--mcp-config", shlex.quote(str(self.mcp_config))]
        if self.system_prompt_file:
            parts += [
                "--append-system-prompt",
                f'"$(cat {shlex.quote(str(self.system_prompt_file))})"',
            ]
        if self.model:
            parts += ["--model", shlex.quote(self.model)]
        return f"cd {shlex.quote(str(self.work_dir))} && " + " ".join(parts)

    def _ensure_locked(self) -> None:
        """Create + ready the session if needed. Caller must hold the lock."""
        if self._session_exists():
            return
        self._ready_flag.unlink(missing_ok=True)
        self._tmux(
            "new-session",
            "-d",
            "-s",
            self.session_name,
            "-x",
            _PANE_WIDTH,
            "-y",
            _PANE_HEIGHT,
            self._start_command(),
        )
        # Bigger scrollback so long replies stay within capture range.
        self._tmux("set-option", "-t", self.session_name, "history-limit", "50000")
        # Pre-create the transcript owner-only: `cat >>` appends and keeps
        # the mode, while letting tmux create it would use the server umask.
        self._pane_log.touch()
        os.chmod(self._pane_log, 0o600)
        self._tmux(
            "pipe-pane",
            "-t",
            self._target,
            f"cat >> {shlex.quote(str(self._pane_log))}",
        )

        deadline = self._clock() + self._startup_timeout
        last_state: PaneState | None = None
        while self._clock() < deadline:
            cap = self._capture()
            state = classify_state(cap)
            # Debounce: only Enter on the transition INTO the trust prompt,
            # never on every poll (avoids stray blank submissions).
            if state == PaneState.TRUST_PROMPT:
                if last_state != PaneState.TRUST_PROMPT:
                    self._send_enter()
                last_state = state
                self._sleep(self._poll_interval)
                continue
            # Bypass-permissions accept screen (fresh config dir): unlike TRUST,
            # the safe default ❯ sits on "1. No, exit", so we must actively pick
            # "2. Yes, I accept". Debounced to the transition like TRUST.
            if state == PaneState.BYPASS_PROMPT:
                if last_state != PaneState.BYPASS_PROMPT:
                    self._tmux("send-keys", "-t", self._target, "2")
                    self._send_enter()
                last_state = state
                self._sleep(self._poll_interval)
                continue
            if state == PaneState.READY:
                self._ready_flag.write_text("ready\n")
                logger.info("Claude session %s is ready", self.session_name)
                return
            last_state = state
            self._sleep(self._poll_interval)
        raise RuntimeError(
            f"session {self.session_name} not ready in {self._startup_timeout}s; "
            f"last state={last_state}; pane tail:\n"
            + "\n".join(self._capture().splitlines()[-8:])
        )

    def ensure_session(self) -> None:
        with self._locked() as got:
            if got:
                self._ensure_locked()

    def is_healthy(self) -> bool:
        return self._session_exists()

    def current_state(self) -> PaneState:
        """Classify the live pane (for the watchdog / doctor)."""
        return classify_state(self._capture())

    def is_working(self) -> bool:
        """True iff the pane shows an active turn (for the watchdog)."""
        return is_working(self._capture())

    def force_recover(self) -> bool:
        """Watchdog entry point: take the lock non-blocking; if free, kill and
        recreate. Returns False if a live ask() currently holds the lock."""
        with self._locked(blocking=False) as got:
            if not got:
                return False
            self._tmux("kill-session", "-t", self.session_name)
            self._ready_flag.unlink(missing_ok=True)
            self._inflight.unlink(missing_ok=True)
            self._ensure_locked()
            return True

    def kill(self) -> None:
        """Tear down the session (lock-guarded). For CLI/teardown use."""
        with self._locked() as got:
            if got:
                self._tmux("kill-session", "-t", self.session_name)
                self._ready_flag.unlink(missing_ok=True)
                self._inflight.unlink(missing_ok=True)

    # ── steering (concurrent input into a live turn) ─────────────────

    def steer(self, text: str) -> None:
        """Type text into the pane WITHOUT taking the pane lock.

        Used to inject guidance into an in-flight turn (the lock is held by
        that turn's ask()). The interactive TUI feeds mid-turn input to the
        model (steer/queue semantics) — VERIFY-LIVE per CLI version.
        """
        self._send_text(text)
        self._send_enter()

    def interrupt(self) -> None:
        """Stop the current response (TUI-native Escape, no lock).

        C-c is deliberately NOT used here: on an idle prompt a C-c starts the
        double-C-c exit sequence; Escape only ever cancels the response.
        """
        self._tmux("send-keys", "-t", self._target, "Escape")

    def is_turn_active(self) -> bool:
        """True iff a turn is in flight (the pane lock is held)."""
        with self._locked(blocking=False) as got:
            return not got

    def is_steerable_turn(self) -> bool:
        """True iff the in-flight turn may receive steering input.

        Maintenance turns (nightly pipeline, doctor canary, /process) tag
        themselves with a ``maint-`` request_id — user text steered into
        them would contaminate the background prompt and never get its own
        answer. A held lock WITHOUT an inflight record is startup/recovery/
        control — also not steerable.
        """
        if not self.is_turn_active():
            return False
        try:
            first = self._inflight.read_text().splitlines()[0]
        except (FileNotFoundError, IndexError):
            return False
        return not first.startswith(MAINT_PREFIX)

    def send_control(self, text: str) -> None:
        """Type a client-side Claude Code command verbatim, fire-and-forget.

        Control commands (/clear, /model, …) produce no model turn and thus
        no marker pair — there is nothing to extract, so don't wait.
        """
        with self._locked() as got:
            if got:
                self._send_text(text)
                self._send_enter()

    def clear(self) -> None:
        """Manual recovery only (durable-state-first: no scheduled clear)."""
        self.send_control("/clear")

    # ── sending ──────────────────────────────────────────────────────

    def _send_text(self, text: str) -> None:
        # Stream the payload to `load-buffer -` over stdin; passing it as an
        # argv element trips tmux's "set-buffer: command too long" on long
        # prompts and the text is silently dropped (session then stalls).
        if not text:
            return  # 0 bytes ⇒ no buffer ⇒ paste-buffer would fail `no buffer`
        buf = f"dbrain_{uuid.uuid4().hex[:6]}"
        self._tmux("load-buffer", "-b", buf, "-", input_text=text)
        self._tmux("paste-buffer", "-t", self._target, "-b", buf, "-d")
        self._sleep(self._paste_settle)

    def _send_prompt(self, prompt: str, rid: str, *, wrap: bool = True) -> None:
        # Markers are written INLINE (mid-sentence) so the input echo never
        # forms a line-anchored pair; only the model's answer does.
        if not wrap:
            self._send_text(prompt)
            self._send_enter()
            return
        payload = (
            f"{prompt}\n\n"
            f"When done, wrap your ENTIRE reply between a line containing only "
            f"<<<R:{rid}>>> and a line containing only <<<E:{rid}>>>."
        )
        self._send_text(payload)
        self._send_enter()

    # ── ask ──────────────────────────────────────────────────────────

    def ask(
        self,
        prompt: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        request_id: str | None = None,
        wrap: bool = True,
    ) -> AskResult:
        """Send a prompt, return the model's reply (or a non-ok status).

        Lock-guarded so concurrent callers serialize on the pane. Never
        raises and never blocks forever: ensure failure → error, rate-limit /
        logged-out short-circuit, a frozen pane (stall) is interrupted, and a
        hard timeout returns a timeout status. request_id is for logging only;
        the marker rid is always freshly generated to avoid stale answers.

        wrap=True (default) appends the marker instruction and extracts the
        reply between the marker pair — the reliable path for model turns.
        wrap=False types the prompt verbatim; completion is the pane sitting
        idle for two consecutive polls and the reply is the chrome-stripped
        pane text (best effort, may include the input echo).
        """
        rid = self._rid_factory()
        log_id = request_id or rid
        with self._locked() as got:
            if not got:  # only happens with non-blocking; blocking=True here
                return AskResult("error", detail="could not acquire pane lock")
            # Claim the turn IMMEDIATELY: a stale inflight from a timed-out
            # earlier turn must not misrepresent this holder to the steering
            # gate while _ensure_locked() spends up to startup_timeout.
            self._inflight.write_text(f"{log_id}\n{self._clock()}\n")
            try:
                self._ensure_locked()
            except Exception as exc:  # noqa: BLE001 — must never escape ask()
                logger.error("ensure_session failed for %s: %s", log_id, exc)
                self._inflight.unlink(missing_ok=True)
                return AskResult("error", detail=f"session start failed: {exc}")

            pre = classify_state(self._capture())
            if pre == PaneState.RATE_LIMITED:
                self._inflight.unlink(missing_ok=True)
                return AskResult("rate_limited")
            if pre == PaneState.LOGGED_OUT:
                self._inflight.unlink(missing_ok=True)
                return AskResult("logged_out")

            self._send_prompt(prompt, rid, wrap=wrap)

            last_active = self._clock()
            last_log_size = self._pane_log_size()
            deadline = self._clock() + timeout
            idle_streak = 0
            while self._clock() < deadline:
                cap = self._capture()
                state = classify_state(cap)
                if state == PaneState.RATE_LIMITED:
                    self._inflight.unlink(missing_ok=True)
                    return AskResult("rate_limited")
                if state == PaneState.LOGGED_OUT:
                    self._inflight.unlink(missing_ok=True)
                    return AskResult("logged_out")
                if wrap:
                    if is_complete(cap, rid):
                        self._inflight.unlink(missing_ok=True)
                        return AskResult("ok", reply=extract_reply(cap, rid))
                elif is_idle(cap):
                    idle_streak += 1
                    if idle_streak >= 2:
                        self._inflight.unlink(missing_ok=True)
                        return AskResult("ok", reply=strip_chrome(cap))
                else:
                    idle_streak = 0

                # The periodic "How is Claude doing?" survey pollutes the
                # chrome and once made the stall detector interrupt a live
                # turn. Dismiss it (0) and never count it as a stall.
                if has_survey_prompt(cap):
                    self._tmux("send-keys", "-t", self._target, "0")
                    last_active = self._clock()
                    self._sleep(self._poll_interval)
                    continue

                # Stall model: silence is NOT a hang signal — a quiet task
                # still shows the working spinner. Stuck == no visible turn
                # (and no completion) for longer than stall_timeout.
                # Two liveness signals: the recognized spinner, OR a growing
                # transcript — pane.log growth is version-proof and survives
                # any future change to the spinner's on-screen text.
                log_size = self._pane_log_size()
                if is_working(cap) or log_size > last_log_size:
                    last_active = self._clock()
                last_log_size = log_size
                if self._clock() - last_active > self._stall_timeout:
                    self._interrupt()
                    # leave inflight as an orphan/stuck signal for the watchdog
                    return AskResult("error", detail="session stalled (no active turn)")
                self._sleep(self._poll_interval)

            # timed out: prompt is still physically in the pane → keep inflight
            return AskResult("timeout", detail=f"no reply in {timeout}s")
