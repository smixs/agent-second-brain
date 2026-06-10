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
    fake = FakeTmuxText([READY, THINKING, "ответ\n" + READY, "ответ\n" + READY], exists=True)
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
