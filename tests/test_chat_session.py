"""Tests for ChatSessionManager — chat messages routed to the shared session."""

import asyncio

from d_brain.services.claude_session import AskResult


class FakeSession:
    def __init__(self, result: AskResult, *, clear_ok: bool = True) -> None:
        self.result = result
        self.prompts: list[str] = []
        self.cleared = 0
        self.hard_resets = 0
        self._clear_ok = clear_ok

    def ask(self, prompt: str, **kwargs) -> AskResult:
        self.prompts.append(prompt)
        return self.result

    def clear(self) -> bool:
        self.cleared += 1
        return self._clear_ok

    def hard_reset(self) -> bool:
        self.hard_resets += 1
        return True


def _manager(tmp_path, result: AskResult):
    from d_brain.services.chat_session import ChatSessionManager

    return ChatSessionManager(tmp_path, session=FakeSession(result))


def test_send_message_returns_reply_on_ok(tmp_path):
    m = _manager(tmp_path, AskResult("ok", reply="привет"))
    reply = asyncio.run(m.send_message(1, "здравствуй"))
    assert reply == "привет"
    assert m._session.prompts == ["здравствуй"]


def test_send_message_maps_rate_limited(tmp_path):
    m = _manager(tmp_path, AskResult("rate_limited"))
    reply = asyncio.run(m.send_message(1, "x"))
    assert "Лимит" in reply


def test_reset_clears_live_session(tmp_path):
    m = _manager(tmp_path, AskResult("ok", reply=""))
    msg = asyncio.run(m.reset(1))
    assert m._session.cleared == 1
    assert "очищен" in msg


def test_reset_reports_a_busy_pane_instead_of_claiming_success(tmp_path):
    """A soft reset waits at most lock_timeout for the pane. When it can't
    have it, the user must be told to escalate — not shown a false 'done'."""
    from d_brain.services.chat_session import ChatSessionManager

    m = ChatSessionManager(
        tmp_path, session=FakeSession(AskResult("ok"), clear_ok=False)
    )
    msg = asyncio.run(m.reset(1))
    assert "/reset" in msg


def test_hard_reset_recreates_the_session(tmp_path):
    m = _manager(tmp_path, AskResult("ok", reply=""))
    msg = asyncio.run(m.hard_reset(1))
    assert m._session.hard_resets == 1
    assert m._session.cleared == 0  # never routed through the lock-taking path
    assert "пересоздана" in msg
