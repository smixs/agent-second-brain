"""Tests for the unified chat handler."""

import asyncio


def test_text_message_goes_through_debounce_buffer():
    """Characterization (pre-v3 behavior): an incoming text lands in the
    per-chat debounce buffer and schedules a delayed flush."""
    from d_brain.bot.handlers import chat

    async def run():
        chat._buffers.clear()
        chat._add_to_buffer(chat_id=10, user_id=1, content="привет", msg_type="text", bot=None)
        buf = chat._buffers[10]
        assert [m.content for m in buf.messages] == ["привет"]
        assert buf.task is not None and not buf.task.done()
        buf.task.cancel()

    asyncio.run(run())


def test_build_prompt_joins_buffered_messages():
    from d_brain.bot.handlers.chat import BufferedMessage, _build_prompt
    from datetime import datetime

    msgs = [
        BufferedMessage("a", "text", datetime(2026, 6, 10, 10, 0)),
        BufferedMessage("b", "voice", datetime(2026, 6, 10, 10, 1)),
    ]
    out = _build_prompt(msgs)
    assert "a" in out and "b" in out and "[voice]" in out
