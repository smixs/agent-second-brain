"""Tests for ClaudeSession orchestration.

The real tmux/subprocess layer is replaced by FakeTmux, which models the
pane as a small state machine and returns scripted capture-pane output.
Clock, sleep and rid generation are injected so polling, timeout
and stall detection are deterministic and fast.
"""

import subprocess
from pathlib import Path

import pytest

from d_brain.services.claude_session import AskResult, ClaudeSession

READY = (
    "────────────────────\n❯\n────────────────────\n"
    "  hello | Opus 4.8 (1M context) | ~/p\n"
    "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
)
TRUST = (
    " Quick safety check: Is this a project you created or one you trust?\n"
    " ❯ 1. Yes, I trust this folder\n   2. No, exit\n"
)
BYPASS = (
    " WARNING: Claude Code running in Bypass Permissions mode\n\n"
    " In Bypass Permissions mode, Claude Code will not ask for your approval.\n"
    " ❯ 1. No, exit\n   2. Yes, I accept\n"
)
THINKING = "  ✻ Working…  (esc to interrupt)\n"
RATE = "  You've reached your usage limit. Your limit resets at 3:00 PM.\n❯\n"
LOGGED_OUT = "  Invalid API key · Please run /login to authenticate.\n❯\n"


def _complete(rid: str, reply: str = "PONG") -> str:
    return f"some echo <<<R:{rid}>>> inline\n<<<R:{rid}>>>\n{reply}\n<<<E:{rid}>>>\n❯\n"


def _inline_echo(rid: str) -> str:
    """Echo of the typed prompt: markers appear INLINE (mid-sentence)."""
    return f"> reply, wrap between <<<R:{rid}>>> and <<<E:{rid}>>> markers\n{THINKING}"


class FakeTmux:
    """Callable stand-in for subprocess.run over `tmux ...`."""

    def __init__(self, capture_script: list[str], exists: bool = False) -> None:
        self._captures = list(capture_script)
        self.exists = exists
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):  # noqa: ANN001
        self.calls.append(args)
        sub = args[1] if args and args[0] == "tmux" else args[0]
        out, rc = "", 0
        if sub == "has-session":
            rc = 0 if self.exists else 1
        elif sub == "new-session":
            self.exists = True
        elif sub == "capture-pane":
            out = (
                self._captures.pop(0)
                if len(self._captures) > 1
                else (self._captures[0] if self._captures else "")
            )
        return subprocess.CompletedProcess(args, rc, stdout=out, stderr="")

    def sent_subcommands(self) -> list[str]:
        return [c[1] for c in self.calls if c and c[0] == "tmux"]

    def sent_keys(self) -> list[list[str]]:
        return [c for c in self.calls if len(c) > 1 and c[1] == "send-keys"]

    def enter_count(self) -> int:
        return sum(1 for c in self.sent_keys() if c[-1] == "Enter")


@pytest.fixture
def clock():
    return {"now": 0.0}


def make_session(
    tmp_path: Path,
    fake: FakeTmux,
    clock: dict,
    *,
    rid: str = "rid00001",
) -> ClaudeSession:
    def sleep_fn(seconds: float) -> None:
        clock["now"] += seconds

    return ClaudeSession(
        session_name="dbrain_test",
        work_dir=tmp_path / "vault",
        runtime_dir=tmp_path / ".dbrain",
        runner=fake,
        sleep_fn=sleep_fn,
        clock_fn=lambda: clock["now"],
        rid_factory=lambda: rid,
        poll_interval=1.0,
        startup_timeout=30.0,
        stall_timeout=10.0,
    )


# ── ensure_session ──────────────────────────────────────────────────────


def test_ensure_session_creates_when_absent(tmp_path, clock):
    fake = FakeTmux([READY], exists=False)
    s = make_session(tmp_path, fake, clock)
    s.ensure_session()
    assert "new-session" in fake.sent_subcommands()
    assert "pipe-pane" in fake.sent_subcommands()
    assert (tmp_path / ".dbrain" / "ready").exists()


def test_ensure_session_noop_when_present(tmp_path, clock):
    fake = FakeTmux([READY], exists=True)
    s = make_session(tmp_path, fake, clock)
    s.ensure_session()
    assert "new-session" not in fake.sent_subcommands()


def test_ensure_session_handles_trust_prompt(tmp_path, clock):
    fake = FakeTmux([TRUST, READY], exists=False)
    s = make_session(tmp_path, fake, clock)
    s.ensure_session()
    assert fake.enter_count() >= 1


def test_ensure_session_does_not_enter_spam_on_trust(tmp_path, clock):
    """Trust persists for several captures; Enter must be debounced to the
    transition, not sent on every poll (M2)."""
    fake = FakeTmux([TRUST, TRUST, TRUST, READY], exists=False)
    s = make_session(tmp_path, fake, clock)
    s.ensure_session()
    assert fake.enter_count() == 1


def _digit_sends(fake: FakeTmux, digit: str) -> int:
    return sum(1 for c in fake.sent_keys() if c[-1] == digit)


def test_ensure_session_accepts_bypass_prompt(tmp_path, clock):
    """Fresh config dir under --dangerously-skip-permissions shows the bypass
    accept screen; the session must actively pick "2. Yes, I accept" (the safe
    default sits on "1. No, exit") and then reach READY."""
    fake = FakeTmux([BYPASS, READY], exists=False)
    s = make_session(tmp_path, fake, clock)
    s.ensure_session()
    assert _digit_sends(fake, "2") == 1
    assert (tmp_path / ".dbrain" / "ready").exists()


def test_ensure_session_does_not_spam_bypass(tmp_path, clock):
    """Bypass persists for several captures; "2" debounced to the transition."""
    fake = FakeTmux([BYPASS, BYPASS, BYPASS, READY], exists=False)
    s = make_session(tmp_path, fake, clock)
    s.ensure_session()
    assert _digit_sends(fake, "2") == 1


def test_ensure_session_raises_if_never_ready(tmp_path, clock):
    fake = FakeTmux([THINKING], exists=False)
    s = make_session(tmp_path, fake, clock)
    with pytest.raises(RuntimeError):
        s.ensure_session()


# ── sending (buffer) ─────────────────────────────────────────────────────


def test_send_text_pipes_long_payload_via_stdin(tmp_path, clock):
    """Regression: a long prompt must be streamed to `tmux load-buffer -` over
    stdin, never passed as an argv element — argv data trips tmux's
    `set-buffer: command too long` and the prompt is silently dropped."""
    recorded: list[tuple[list[str], dict]] = []

    def runner(args, **kwargs):
        recorded.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    s = make_session(tmp_path, runner, clock)
    big = "x" * 200_000
    s._send_text(big)

    loads = [
        (a, k)
        for (a, k) in recorded
        if len(a) > 1 and a[1] in ("set-buffer", "load-buffer")
    ]
    assert loads, "expected a buffer-load tmux call"
    args, kwargs = loads[0]
    assert big not in args, "payload must not be passed as an argv element"
    assert kwargs.get("input") == big, "payload must be piped via stdin"
    assert args[1] == "load-buffer" and "-" in args


def test_send_text_noop_on_empty(tmp_path, clock):
    """`load-buffer -` of zero bytes creates no buffer, so a following
    paste-buffer would fail `no buffer` — empty text must send nothing."""
    recorded: list[list[str]] = []

    def runner(args, **kwargs):
        recorded.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    s = make_session(tmp_path, runner, clock)
    s._send_text("")
    subs = [a[1] for a in recorded if len(a) > 1 and a[0] == "tmux"]
    assert "load-buffer" not in subs and "paste-buffer" not in subs


# ── ask ─────────────────────────────────────────────────────────────────


def test_ask_returns_reply_on_completion(tmp_path, clock):
    rid = "abcd0001"
    fake = FakeTmux([READY, THINKING, _complete(rid)], exists=True)
    s = make_session(tmp_path, fake, clock, rid=rid)
    res = s.ask("ping", timeout=60)
    assert isinstance(res, AskResult)
    assert res.ok
    assert res.reply == "PONG"


def test_ask_ignores_inline_echo_contamination(tmp_path, clock):
    """The echoed prompt has inline markers; ask must NOT complete on it,
    only on the real line-anchored answer (H1 at session level)."""
    rid = "echo0001"
    fake = FakeTmux([READY, _inline_echo(rid), _complete(rid)], exists=True)
    s = make_session(tmp_path, fake, clock, rid=rid)
    res = s.ask("ping", timeout=60)
    assert res.reply == "PONG"


def test_ask_detects_rate_limit_without_hanging(tmp_path, clock):
    fake = FakeTmux([RATE], exists=True)
    s = make_session(tmp_path, fake, clock)
    res = s.ask("ping", timeout=60)
    assert res.status == "rate_limited"
    assert not res.ok


def test_ask_detects_logged_out(tmp_path, clock):
    fake = FakeTmux([LOGGED_OUT], exists=True)
    s = make_session(tmp_path, fake, clock)
    res = s.ask("ping", timeout=60)
    assert res.status == "logged_out"


def test_ask_times_out_when_no_reply(tmp_path, clock):
    fake = FakeTmux([READY, THINKING], exists=True)
    # the working spinner is visible, so it's a timeout, not a stall
    s = make_session(tmp_path, fake, clock)
    res = s.ask("ping", timeout=3)
    assert res.status == "timeout"


def test_ask_detects_stall_and_interrupts(tmp_path, clock):
    """v3.0 stall model: a turn with NO visible work (no 'esc to interrupt'
    spinner, no markers) longer than stall_timeout is stuck — the prompt got
    eaten or the turn is waiting on something undrivable. Interrupt promptly."""
    fake = FakeTmux([READY, READY], exists=True)  # never shows work
    s = make_session(tmp_path, fake, clock)
    res = s.ask("ping", timeout=600)
    assert res.status == "error"
    assert "stall" in (res.detail or "").lower()
    assert any(c[-1] == "C-c" for c in fake.sent_keys())


def test_ask_long_silent_work_not_interrupted(tmp_path, clock):
    """The working spinner is visible → the turn is ALIVE however quiet it
    is. No C-c; the hard timeout (not a stall) ends the wait."""
    fake = FakeTmux([READY, THINKING], exists=True)
    s = make_session(tmp_path, fake, clock)
    res = s.ask("ping", timeout=30)
    assert res.status == "timeout"
    assert not any(c[-1] == "C-c" for c in fake.sent_keys())


def test_ask_returns_error_when_ensure_fails(tmp_path, clock):
    """ensure_session failing must surface as AskResult('error'), never an
    exception out of ask() (C2)."""
    fake = FakeTmux([THINKING], exists=False)  # never becomes READY
    s = make_session(tmp_path, fake, clock)
    res = s.ask("ping", timeout=60)
    assert res.status == "error"


def test_ask_leaves_inflight_orphan_on_timeout(tmp_path, clock):
    """A timed-out prompt is still physically in the pane; inflight marker
    must persist as a stuck-signal (M6)."""
    fake = FakeTmux([READY, THINKING], exists=True)
    s = make_session(tmp_path, fake, clock)
    s.ask("ping", timeout=3)
    assert (tmp_path / ".dbrain" / "inflight").exists()


def test_ask_clears_inflight_on_success(tmp_path, clock):
    rid = "abcd0005"
    fake = FakeTmux([READY, _complete(rid)], exists=True)
    s = make_session(tmp_path, fake, clock, rid=rid)
    s.ask("ping", timeout=60)
    assert not (tmp_path / ".dbrain" / "inflight").exists()


def test_ask_sends_prompt_via_buffer_then_enter(tmp_path, clock):
    rid = "abcd0006"
    fake = FakeTmux([READY, _complete(rid)], exists=True)
    s = make_session(tmp_path, fake, clock, rid=rid)
    s.ask("do the thing", timeout=60)
    assert "paste-buffer" in fake.sent_subcommands()
    assert any(c[-1] == "Enter" for c in fake.sent_keys())


# ── health ──────────────────────────────────────────────────────────────


def test_is_healthy_true_when_session_exists(tmp_path, clock):
    fake = FakeTmux([READY], exists=True)
    s = make_session(tmp_path, fake, clock)
    assert s.is_healthy() is True


def test_is_healthy_false_when_absent(tmp_path, clock):
    fake = FakeTmux([READY], exists=False)
    s = make_session(tmp_path, fake, clock)
    assert s.is_healthy() is False


def test_kill_sends_kill_session(tmp_path, clock):
    fake = FakeTmux([READY], exists=True)
    s = make_session(tmp_path, fake, clock)
    s.kill()
    assert "kill-session" in fake.sent_subcommands()




# ── optional markers (wrap=False) + idle-based completion ──────────────────


class FakeTmuxText(FakeTmux):
    """FakeTmux that also records text streamed to load-buffer."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.texts: list[str] = []

    def __call__(self, args, **kwargs):  # noqa: ANN001
        if kwargs.get("input") is not None:
            self.texts.append(kwargs["input"])
        return super().__call__(args, **kwargs)


def test_ask_wrap_false_does_not_append_marker_instruction(tmp_path, clock):
    fake = FakeTmuxText(
        [READY, THINKING, "ответ\n" + READY, "ответ\n" + READY], exists=True
    )
    (tmp_path / ".dbrain").mkdir()
    (tmp_path / ".dbrain" / "ready").touch()
    s = make_session(tmp_path, fake, clock)
    s.ask("/clear", timeout=30, wrap=False)
    assert fake.texts, "prompt was not streamed to the pane"
    assert "<<<R:" not in fake.texts[0]
    assert "When done" not in fake.texts[0]


def test_ask_wrap_false_completes_on_idle(tmp_path, clock):
    fake = FakeTmuxText(
        [READY, THINKING, THINKING, "ответ модели\n" + READY, "ответ модели\n" + READY],
        exists=True,
    )
    (tmp_path / ".dbrain").mkdir()
    (tmp_path / ".dbrain" / "ready").touch()
    s = make_session(tmp_path, fake, clock)
    res = s.ask("сделай дело", timeout=30, wrap=False)
    assert res.ok, res
    assert "ответ модели" in (res.reply or "")
    assert "bypass permissions" not in (res.reply or "")


def test_ask_wrap_true_still_appends_markers(tmp_path, clock):
    rid = "rid00001"
    fake = FakeTmuxText([READY, _complete(rid)], exists=True)
    (tmp_path / ".dbrain").mkdir()
    (tmp_path / ".dbrain" / "ready").touch()
    s = make_session(tmp_path, fake, clock)
    res = s.ask("ping", timeout=30)
    assert res.ok and res.reply == "PONG"
    assert fake.texts and f"<<<R:{rid}>>>" in fake.texts[0]


# ── steering: inject input into a LIVE turn (no exclusive lock) ─────────────


def test_steer_sends_text_while_lock_is_held(tmp_path, clock):
    """steer() must work WHILE an ask() holds the pane lock — it types into
    the live turn, so it must not take the blocking lock (no deadlock)."""
    import fcntl
    import os

    fake = FakeTmuxText([READY], exists=True)
    s = make_session(tmp_path, fake, clock)
    lock_fd = os.open(tmp_path / ".dbrain" / "pane.lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)  # simulate an in-flight ask()
    try:
        s.steer("уточнение: пиши короче")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    assert fake.texts and "уточнение" in fake.texts[0]
    assert fake.enter_count() >= 1


def test_interrupt_sends_escape(tmp_path, clock):
    """interrupt() uses the TUI-native Escape (stops the current response);
    C-c is reserved for the stall path (double C-c would begin app exit)."""
    fake = FakeTmux([READY], exists=True)
    s = make_session(tmp_path, fake, clock)
    s.interrupt()
    assert any(c[-1] == "Escape" for c in fake.sent_keys())
    assert not any(c[-1] == "C-c" for c in fake.sent_keys())


def test_is_turn_active_reflects_lock_state(tmp_path, clock):
    import fcntl
    import os

    fake = FakeTmux([READY], exists=True)
    s = make_session(tmp_path, fake, clock)
    assert s.is_turn_active() is False  # lock free → no ask in flight

    lock_fd = os.open(tmp_path / ".dbrain" / "pane.lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        assert s.is_turn_active() is True
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


# ── runtime privacy: the pane transcript is owner-only ──────────────────


def test_runtime_dir_is_owner_only(tmp_path, clock):
    fake = FakeTmux([READY], exists=False)
    make_session(tmp_path, fake, clock)
    mode = (tmp_path / ".dbrain").stat().st_mode & 0o777
    assert mode == 0o700


def test_pane_log_precreated_owner_only_before_pipe(tmp_path, clock):
    # pipe-pane appends the FULL Claude transcript via `cat >>` under the
    # tmux server's umask — the file must ALREADY be 0600 when pipe-pane
    # starts, not fixed up afterwards.
    log = tmp_path / ".dbrain" / "pane.log"
    seen = {}

    class Spy(FakeTmux):
        def __call__(self, args, **kwargs):  # noqa: ANN001
            if len(args) > 1 and args[1] == "pipe-pane":
                seen["mode_at_pipe"] = (
                    log.stat().st_mode & 0o777 if log.exists() else None
                )
            return super().__call__(args, **kwargs)

    s = make_session(tmp_path, Spy([READY], exists=False), clock)
    s.ensure_session()
    assert seen["mode_at_pipe"] == 0o600
    assert (log.stat().st_mode & 0o777) == 0o600


# ── steering gate: maintenance turns must not swallow user input ────────


def _hold_pane_lock(s):
    import fcntl

    fh = open(s._pane_lock, "w")
    fcntl.flock(fh, fcntl.LOCK_EX)
    return fh


def test_is_steerable_turn_distinguishes_chat_from_maintenance(tmp_path, clock):
    s = make_session(tmp_path, FakeTmux([READY]), clock)
    inflight = tmp_path / ".dbrain" / "inflight"

    assert s.is_steerable_turn() is False  # idle: nothing to steer

    fh = _hold_pane_lock(s)
    try:
        # lock held but no inflight → startup/recovery/control, not a turn
        assert s.is_steerable_turn() is False
        inflight.write_text("rid12345\n0.0\n")
        assert s.is_steerable_turn() is True  # a chat turn
        inflight.write_text("maint-daily\n0.0\n")
        assert s.is_steerable_turn() is False  # the nightly pipeline
    finally:
        fh.close()


def test_inflight_claimed_before_session_startup(tmp_path, clock):
    # A stale inflight left by a timed-out chat turn must not misrepresent
    # the new holder to the steering gate while session startup (up to
    # startup_timeout) is still running.
    inflight = tmp_path / ".dbrain" / "inflight"
    seen = {}

    class Spy(FakeTmux):
        def __call__(self, args, **kwargs):  # noqa: ANN001
            if len(args) > 1 and args[1] == "new-session":
                seen["at_startup"] = (
                    inflight.read_text() if inflight.exists() else None
                )
            return super().__call__(args, **kwargs)

    fake = Spy([READY, READY, _complete("rid00001")], exists=False)
    s = make_session(tmp_path, fake, clock)
    inflight.write_text("stale-chat-rid\n0.0\n")  # leftover from a timeout

    s.ask("nightly run", request_id="maint-process")

    assert seen["at_startup"] is not None
    assert seen["at_startup"].startswith("maint-process")


def test_ask_dismisses_feedback_survey_instead_of_stalling(tmp_path, clock):
    # Claude Code periodically shows "How is Claude doing this session?" —
    # it polluted the chrome, the stall detector fired Escape and the user
    # got a session error. The session must press 0 (Dismiss) and carry on.
    survey = (
        "● How is Claude doing this session? (optional)\n"
        "  1: Bad    2: Fine   3: Good   0: Dismiss\n" + READY
    )
    fake = FakeTmux(
        [READY, survey, THINKING, _complete("rid00001")], exists=True
    )
    s = make_session(tmp_path, fake, clock)
    res = s.ask("привет")
    assert res.status == "ok"
    pressed = [c for c in fake.sent_keys() if c[-1] == "0"]
    assert pressed, "survey was not dismissed with 0"
    escapes = [c for c in fake.sent_keys() if c[-1] == "Escape"]
    assert not escapes, "stall interrupt fired instead of dismissing survey"


def test_growing_pane_log_prevents_false_stall(tmp_path, clock):
    # Version-proof liveness: even if a future spinner format is
    # unrecognized, a transcript that keeps growing means the brain is
    # working — it must not be killed as a stall.
    log = tmp_path / ".dbrain" / "pane.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")
    busy = "thinking, but with a spinner we do not recognize\n"
    fake = FakeTmux([READY] + [busy] * 20 + [_complete("rid00001")], exists=True)
    s = make_session(tmp_path, fake, clock)  # stall_timeout=10, poll=1

    def grow_sleep(seconds: float) -> None:
        clock["now"] += seconds
        with log.open("a") as f:
            f.write("x" * 100)  # transcript advancing → alive

    s._sleep = grow_sleep
    res = s.ask("long task")
    assert res.status == "ok"
    assert not any(c[-1] in ("Escape", "C-c") for c in fake.sent_keys())


def test_static_pane_log_and_no_spinner_still_stalls(tmp_path, clock):
    # The fallback must not disable stall detection: a genuinely wedged
    # turn (no spinner, transcript frozen) still gets interrupted.
    log = tmp_path / ".dbrain" / "pane.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("frozen")
    busy = "no spinner, no markers, nothing changing\n"
    fake = FakeTmux([READY] + [busy] * 40, exists=True)
    s = make_session(tmp_path, fake, clock)
    res = s.ask("x", timeout=600)
    assert res.status == "error"
    assert "stall" in (res.detail or "").lower()
