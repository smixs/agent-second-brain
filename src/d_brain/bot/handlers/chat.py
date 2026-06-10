"""Unified private chat handler with persistent Claude sessions.

Voice + text only (v3.0): replaces the legacy split handlers for private chats.
All messages are saved to daily (safety net) and routed through
ChatSessionManager for Claude to process and respond.
"""

import asyncio
import html
import logging
from dataclasses import dataclass, field
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from d_brain.bot.formatters import (
    sanitize_telegram_html,
    truncate_html,
    validate_telegram_html,
)
from d_brain.config import get_settings
from d_brain.services.chat_session import ChatSessionManager
from d_brain.services.session import SessionStore
from d_brain.services.storage import VaultStorage
from d_brain.services.transcription import DeepgramTranscriber

router = Router(name="chat")
logger = logging.getLogger(__name__)

# Only handle private chats — groups are handled by group.py
router.message.filter(F.chat.type == ChatType.PRIVATE)

DEBOUNCE_SECONDS = 5.0  # 5 sec debounce
MAX_RESPONSE_LENGTH = 4096


@dataclass
class BufferedMessage:
    """Single message in the debounce buffer."""

    content: str
    msg_type: str
    timestamp: datetime


@dataclass
class DebounceBuffer:
    """Per-chat debounce buffer."""

    messages: list[BufferedMessage] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    chat_id: int = 0
    user_id: int = 0


# Module-level state
_buffers: dict[int, DebounceBuffer] = {}
_manager: ChatSessionManager | None = None


def _get_manager() -> ChatSessionManager:
    """Lazy-init ChatSessionManager singleton."""
    global _manager  # noqa: PLW0603
    if _manager is None:
        settings = get_settings()
        _manager = ChatSessionManager(settings.vault_path)
    return _manager


def _get_buffer(chat_id: int, user_id: int) -> DebounceBuffer:
    """Get or create buffer for chat."""
    if chat_id not in _buffers:
        _buffers[chat_id] = DebounceBuffer(chat_id=chat_id, user_id=user_id)
    return _buffers[chat_id]


def _add_to_buffer(
    chat_id: int, user_id: int, content: str, msg_type: str, bot: Bot
) -> None:
    """Add message to debounce buffer and reset timer."""
    buf = _get_buffer(chat_id, user_id)
    buf.messages.append(
        BufferedMessage(
            content=content,
            msg_type=msg_type,
            timestamp=datetime.now(),
        )
    )

    # Cancel existing debounce task
    if buf.task and not buf.task.done():
        buf.task.cancel()

    # Start new debounce task
    buf.task = asyncio.create_task(_debounce_flush(chat_id, bot))


async def _debounce_flush(chat_id: int, bot: Bot) -> None:
    """Wait for debounce period, then flush buffer to Claude."""
    try:
        await asyncio.sleep(DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return

    buf = _buffers.get(chat_id)
    if not buf or not buf.messages:
        return

    messages = buf.messages[:]
    buf.messages.clear()
    user_id = buf.user_id

    prompt = _build_prompt(messages)

    # Typing indicator loop
    typing_task = asyncio.create_task(_typing_loop(bot, chat_id))

    try:
        manager = _get_manager()
        response = await manager.send_message(user_id, prompt)

        if response:
            await _send_response(bot, chat_id, response)
        else:
            logger.warning("Empty response from Claude for user %d, retrying...", user_id)
            # Retry once before giving up — don't reset session on first empty
            response = await manager.send_message(user_id, prompt)
            if response:
                await _send_response(bot, chat_id, response)
            else:
                logger.warning("Empty response after retry for user %d", user_id)
                await bot.send_message(
                    chat_id,
                    "Claude не ответил дважды. Повтори сообщение.",
                )

    except Exception as e:
        logger.exception("Chat session error for user %d", user_id)
        error_text = f"Error: {html.escape(str(e)[:200])}"
        try:
            await bot.send_message(chat_id, error_text)
        except Exception:
            logger.exception("Failed to send error message")
    finally:
        typing_task.cancel()


def _build_prompt(messages: list[BufferedMessage]) -> str:
    """Combine buffered messages into a single prompt."""
    if len(messages) == 1:
        msg = messages[0]
        if msg.msg_type == "text":
            return msg.content
        return f"[{msg.msg_type}] {msg.content}"

    parts = []
    for msg in messages:
        time_str = msg.timestamp.strftime("%H:%M")
        parts.append(f"[{time_str}] [{msg.msg_type}] {msg.content}")
    return "\n".join(parts)


async def _typing_loop(bot: Bot, chat_id: int) -> None:
    """Send typing action every 4 seconds while processing."""
    try:
        while True:
            await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def _send_response(bot: Bot, chat_id: int, text: str) -> None:
    """Send response, splitting if too long for Telegram."""
    sanitized = sanitize_telegram_html(text)
    if not validate_telegram_html(sanitized):
        sanitized = html.escape(text)

    if len(sanitized) <= MAX_RESPONSE_LENGTH:
        try:
            await bot.send_message(chat_id, sanitized)
        except Exception:
            # Fallback: send without HTML
            await bot.send_message(chat_id, sanitized, parse_mode=None)
        return

    # Split into chunks
    chunks = _split_text(sanitized, MAX_RESPONSE_LENGTH)
    for chunk in chunks:
        try:
            await bot.send_message(chat_id, chunk)
        except Exception:
            await bot.send_message(chat_id, chunk, parse_mode=None)
        await asyncio.sleep(0.3)


def _split_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks respecting Telegram limits."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        chunk = truncate_html(remaining, max_len)
        chunks.append(chunk)
        # Move past what we consumed
        consumed = len(chunk.rstrip(".").rstrip())
        if consumed == 0:
            # Safety: force split to avoid infinite loop
            chunks[-1] = remaining[:max_len]
            remaining = remaining[max_len:]
        else:
            remaining = remaining[consumed:].lstrip()
    return chunks


# --- Handlers ---


@router.message(F.voice)
async def handle_chat_voice(message: Message, bot: Bot) -> None:
    """Handle voice messages in private chat."""
    if not message.voice or not message.from_user:
        return

    settings = get_settings()
    storage = VaultStorage(settings.vault_path)
    transcriber = DeepgramTranscriber(settings.deepgram_api_key)

    try:
        file = await bot.get_file(message.voice.file_id)
        if not file.file_path:
            await message.answer("Failed to download voice")
            return

        file_bytes = await bot.download_file(file.file_path)
        if not file_bytes:
            await message.answer("Failed to download voice")
            return

        transcript = await transcriber.transcribe(file_bytes.read())
        if not transcript:
            await message.answer("Could not transcribe audio")
            return

        # Safety net: save to daily
        timestamp = datetime.fromtimestamp(message.date.timestamp())
        storage.append_to_daily(transcript, timestamp, "[voice]")

        # Log to session
        session = SessionStore(settings.vault_path)
        session.append(
            message.from_user.id,
            "voice",
            text=transcript,
            duration=message.voice.duration,
            msg_id=message.message_id,
        )

        # Add to debounce buffer
        _add_to_buffer(
            message.chat.id, message.from_user.id, transcript, "voice", bot
        )

    except Exception as e:
        logger.exception("Error processing voice in chat")
        await message.answer(f"Error: {e}")


@router.message(F.text, lambda m: not m.text.startswith("/"))
async def handle_chat_text(message: Message, bot: Bot) -> None:
    """Handle text messages in private chat (excluding commands)."""
    if not message.text or not message.from_user:
        return

    settings = get_settings()
    storage = VaultStorage(settings.vault_path)

    # Safety net: save to daily
    timestamp = datetime.fromtimestamp(message.date.timestamp())
    storage.append_to_daily(message.text, timestamp, "[text]")

    # Log to session
    session = SessionStore(settings.vault_path)
    session.append(
        message.from_user.id,
        "text",
        text=message.text,
        msg_id=message.message_id,
    )

    # Add to debounce buffer
    _add_to_buffer(
        message.chat.id, message.from_user.id, message.text, "text", bot
    )
