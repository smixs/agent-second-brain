"""Tests for the unified chat handler (v3.0: immediate routing, no debounce)."""

import asyncio


class FakeManager:
    def __init__(self, reply="ответ"):
        self.reply = reply
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, user_id: int, prompt: str) -> str:
        self.sent.append((user_id, prompt))
        return self.reply


class FakeBot:
    def __init__(self):
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))

    async def send_chat_action(self, chat_id, action):
        pass


def test_text_message_routed_immediately(monkeypatch):
    """v3.0: an incoming message reaches the session manager immediately —
    no debounce buffer, no delayed flush."""
    from d_brain.bot.handlers import chat

    mgr = FakeManager(reply="<b>готово</b>")
    monkeypatch.setattr(chat, "_get_manager", lambda: mgr)
    bot = FakeBot()

    asyncio.run(chat._process_and_reply(bot, chat_id=10, user_id=1, prompt="привет"))

    assert mgr.sent == [(1, "привет")]
    assert bot.messages and "готово" in bot.messages[0][1]


def test_no_debounce_infrastructure_left():
    """The debounce buffer is fully removed."""
    from d_brain.bot.handlers import chat

    for name in ("DEBOUNCE_SECONDS", "DebounceBuffer", "_add_to_buffer", "_debounce_flush", "_buffers"):
        assert not hasattr(chat, name), f"zombie debounce symbol: {name}"


# ── slash commands split by BEHAVIOR, not by leading "/" ───────────────────


def test_classify_command_skill_is_normal_turn():
    from d_brain.bot.handlers.chat import classify_command

    assert classify_command("/vault-note сохрани мысль") == "turn"
    assert classify_command("привет, как дела?") == "turn"


def test_classify_command_control_is_fire_and_forget():
    from d_brain.bot.handlers.chat import classify_command

    assert classify_command("/clear") == "control"
    assert classify_command("/model sonnet") == "control"


def test_classify_command_tui_is_unsupported():
    from d_brain.bot.handlers.chat import classify_command

    assert classify_command("/agents") == "tui"
    assert classify_command("/config") == "tui"
    assert classify_command("/login") == "tui"


def test_control_command_dispatches_fire_and_forget(monkeypatch):
    from d_brain.bot.handlers import chat

    class Mgr(FakeManager):
        def __init__(self):
            super().__init__()
            self.controls: list[str] = []

        async def send_control(self, text: str) -> None:
            self.controls.append(text)

    mgr = Mgr()
    monkeypatch.setattr(chat, "_get_manager", lambda: mgr)
    bot = FakeBot()

    asyncio.run(chat._dispatch_text(bot, chat_id=10, user_id=1, text="/clear"))

    assert mgr.controls == ["/clear"]
    assert mgr.sent == []  # no marker turn started
    assert bot.messages  # got an acknowledgement


def test_tui_command_rejected_with_hint(monkeypatch):
    from d_brain.bot.handlers import chat

    mgr = FakeManager()
    monkeypatch.setattr(chat, "_get_manager", lambda: mgr)
    bot = FakeBot()

    asyncio.run(chat._dispatch_text(bot, chat_id=10, user_id=1, text="/agents"))

    assert mgr.sent == []
    assert bot.messages and "attach" in bot.messages[0][1]
