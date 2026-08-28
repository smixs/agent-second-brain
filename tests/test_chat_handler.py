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

    zombies = ("DEBOUNCE_SECONDS", "DebounceBuffer", "_add_to_buffer",
               "_debounce_flush", "_buffers")
    for name in zombies:
        assert not hasattr(chat, name), f"zombie debounce symbol: {name}"


# ── slash commands split by BEHAVIOR, not by leading "/" ───────────────────


def test_classify_command_skill_is_normal_turn():
    from d_brain.bot.handlers.chat import classify_command

    assert classify_command("/vault-note сохрани мысль") == "turn"
    assert classify_command("привет, как дела?") == "turn"


def test_classify_command_control_is_fire_and_forget():
    from d_brain.bot.handlers.chat import classify_command

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

    asyncio.run(chat._dispatch_text(bot, chat_id=10, user_id=1, text="/model sonnet"))

    assert mgr.controls == ["/model sonnet"]
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


# ── concurrent input: steer / interrupt / queue-as-ask ─────────────────────


def test_classify_concurrent_input_modes():
    from d_brain.bot.handlers.chat import classify_concurrent_input

    assert classify_concurrent_input("привет", turn_active=False) == "ask"
    assert classify_concurrent_input("пиши короче", turn_active=True) == "steer"
    assert classify_concurrent_input("стоп", turn_active=True) == "interrupt"
    assert classify_concurrent_input("/stop", turn_active=True) == "interrupt"
    assert classify_concurrent_input("стоп", turn_active=False) == "ask"


class SteerableManager(FakeManager):
    def __init__(self, *, active=False):
        super().__init__()
        self.active = active
        self.steered: list[str] = []
        self.interrupts = 0

    def is_turn_active(self) -> bool:
        return self.active

    def is_steerable_turn(self) -> bool:
        return self.active  # a plain chat turn — steerable while active

    async def steer(self, text: str) -> None:
        self.steered.append(text)

    async def interrupt(self) -> None:
        self.interrupts += 1


def test_plain_text_during_active_turn_steers(monkeypatch):
    from d_brain.bot.handlers import chat

    mgr = SteerableManager(active=True)
    monkeypatch.setattr(chat, "_get_manager", lambda: mgr)
    bot = FakeBot()
    asyncio.run(chat._dispatch_text(bot, chat_id=10, user_id=1, text="пиши короче"))
    assert mgr.steered == ["пиши короче"]
    assert mgr.sent == []  # no new turn started


def test_stop_word_interrupts_active_turn(monkeypatch):
    from d_brain.bot.handlers import chat

    mgr = SteerableManager(active=True)
    monkeypatch.setattr(chat, "_get_manager", lambda: mgr)
    bot = FakeBot()
    asyncio.run(chat._dispatch_text(bot, chat_id=10, user_id=1, text="стоп"))
    assert mgr.interrupts == 1
    assert mgr.sent == [] and mgr.steered == []


def test_text_when_idle_goes_to_normal_turn(monkeypatch):
    from d_brain.bot.handlers import chat

    mgr = SteerableManager(active=False)
    monkeypatch.setattr(chat, "_get_manager", lambda: mgr)
    bot = FakeBot()
    asyncio.run(chat._dispatch_text(bot, chat_id=10, user_id=1, text="привет"))
    assert mgr.sent == [(1, "привет")]
    assert mgr.steered == []


# ── media input: photo / document / video / audio (v3.0.x) ────────────────


class _Stub:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_extract_media_photo_takes_largest():
    from d_brain.bot.handlers.chat import extract_media

    msg = _Stub(
        photo=[_Stub(file_id="small"), _Stub(file_id="big")],
        document=None, video=None, audio=None, animation=None, video_note=None,
    )
    kind, file_id, ext, name = extract_media(msg)
    assert (kind, file_id, ext) == ("photo", "big", "jpg")


def test_extract_media_document_keeps_name_and_ext():
    from d_brain.bot.handlers.chat import extract_media

    doc = _Stub(file_id="d1", file_name="report Q2.pdf")
    msg = _Stub(photo=None, document=doc, video=None, audio=None,
                animation=None, video_note=None)
    kind, file_id, ext, name = extract_media(msg)
    assert (kind, file_id, ext, name) == ("document", "d1", "pdf", "report Q2.pdf")


def test_extract_media_video_note_is_mp4():
    from d_brain.bot.handlers.chat import extract_media

    msg = _Stub(photo=None, document=None, video=None, audio=None,
                animation=None, video_note=_Stub(file_id="v1"))
    kind, file_id, ext, name = extract_media(msg)
    assert (kind, ext) == ("video_note", "mp4")


def test_forward_note_variants():
    from d_brain.bot.handlers.chat import forward_note

    user = _Stub(sender_user=_Stub(full_name="Ivan Petrov"))
    assert "Ivan Petrov" in forward_note(user)
    channel = _Stub(sender_user=None, chat=_Stub(title="AI News"))
    assert "AI News" in forward_note(channel)
    hidden = _Stub(sender_user=None, chat=None, sender_user_name="Hidden Guy")
    assert "Hidden Guy" in forward_note(hidden)
    assert forward_note(None) == ""


def test_build_media_prompt_contract():
    from d_brain.bot.handlers.chat import build_media_prompt

    p = build_media_prompt(
        kind="document",
        rel_path="attachments/2026-06-10/img-120000.pdf",
        original_name="report.pdf",
        caption="квартальный отчёт",
        fwd="[переслано от: Ivan]\n",
    )
    assert "attachments/2026-06-10/img-120000.pdf" in p
    assert "report.pdf" in p
    assert "квартальный отчёт" in p
    assert "Ivan" in p
    # the brain must be told to actually open the file
    assert "Read" in p or "прочитай" in p.lower() or "посмотри" in p.lower()


def test_unsupported_content_reply_exists():
    from d_brain.bot.handlers.chat import UNSUPPORTED_REPLY

    assert "голос" in UNSUPPORTED_REPLY or "voice" in UNSUPPORTED_REPLY.lower()


# ── blind-review fixes: collisions, albums, attribution, escaping ──────────


def test_save_attachment_never_overwrites_same_second(tmp_path):
    from datetime import date, datetime

    from d_brain.services.storage import VaultStorage

    s = VaultStorage(tmp_path)
    ts = datetime(2026, 6, 10, 12, 0, 0)
    p1 = s.save_attachment(b"one", date(2026, 6, 10), ts, "jpg")
    p2 = s.save_attachment(b"two", date(2026, 6, 10), ts, "jpg")
    assert p1 != p2
    assert (tmp_path / "attachments/2026-06-10").glob("*")
    assert (tmp_path / p1).read_bytes() == b"one"
    assert (tmp_path / p2).read_bytes() == b"two"


def test_forward_note_anonymous_group_admin():
    from d_brain.bot.handlers.chat import forward_note

    origin = _Stub(sender_user=None, chat=None, sender_chat=_Stub(title="Work Chat"),
                   sender_user_name=None)
    assert "Work Chat" in forward_note(origin)


def test_extract_media_sanitizes_hostile_extension():
    from d_brain.bot.handlers.chat import extract_media

    doc = _Stub(file_id="d1", file_name="x.a/b")
    msg = _Stub(photo=None, document=doc, video=None, audio=None,
                animation=None, video_note=None)
    _, _, ext, _ = extract_media(msg)
    assert "/" not in ext and "\\" not in ext


def test_reset_commands_are_not_control_commands():
    """commands.router intercepts /new, /clear, /compact and /reset earlier.
    Leaving them in _CONTROL fired them blindly into the pane and answered
    "sent" even when the pane was wedged — the opposite of what a user
    typing /clear at a stuck bot needs."""
    from d_brain.bot.handlers.chat import classify_command

    for cmd in ("/compact", "/clear", "/new", "/reset"):
        assert classify_command(cmd) == "turn", cmd


def test_album_items_flush_as_single_prompt(monkeypatch):
    from d_brain.bot.handlers import chat

    mgr = FakeManager(reply="ok")
    monkeypatch.setattr(chat, "_get_manager", lambda: mgr)
    monkeypatch.setattr(chat, "ALBUM_SETTLE", 0.01)
    bot = FakeBot()

    async def run():
        await chat.queue_album_item(
            bot, chat_id=10, user_id=1, group_id="g1",
            item={"kind": "photo", "rel_path": "attachments/a.jpg",
                  "caption": "подпись", "fwd": ""},
        )
        await chat.queue_album_item(
            bot, chat_id=10, user_id=1, group_id="g1",
            item={"kind": "photo", "rel_path": "attachments/b.jpg",
                  "caption": "", "fwd": ""},
        )
        await asyncio.sleep(0.1)

    asyncio.run(run())
    assert len(mgr.sent) == 1
    prompt = mgr.sent[0][1]
    assert "attachments/a.jpg" in prompt and "attachments/b.jpg" in prompt
    assert "подпись" in prompt


def test_text_during_maintenance_turn_gets_busy_reply(monkeypatch):
    """A message while the nightly pipeline / doctor holds the session must
    NOT be steered into the maintenance turn — the user gets a busy reply."""
    from d_brain.bot.handlers import chat

    class MaintenanceManager(SteerableManager):
        def is_steerable_turn(self) -> bool:
            return False

    mgr = MaintenanceManager(active=True)
    monkeypatch.setattr(chat, "_get_manager", lambda: mgr)
    bot = FakeBot()
    asyncio.run(chat._dispatch_text(bot, chat_id=10, user_id=1, text="пиши короче"))
    assert mgr.steered == []  # nothing injected into the pipeline turn
    assert mgr.sent == []  # and no new turn forced past the lock
    assert bot.messages and "обслуживание" in bot.messages[0][1].lower()
