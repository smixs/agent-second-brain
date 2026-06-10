"""Persistent chat session manager — backed by ONE interactive Claude session.

Migrated from per-user `claude -p --resume` (which moves to the paid Agent SDK
credit on 2026-06-15) to a single long-lived interactive tmux session shared
across the bot. Conversational continuity lives in the live session itself
plus the vault (durable-state-first), so per-user --resume bookkeeping is
gone. The public interface (send_message / reset / compact) is unchanged so
the chat handlers don't need to change.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from d_brain.config import get_settings
from d_brain.services.runtime import get_ask_lock, get_session

logger = logging.getLogger(__name__)

_STATUS_MESSAGES = {
    "rate_limited": "⏳ Лимит подписки исчерпан. Вернусь, когда он обновится.",
    "logged_out": "🔑 Нужен повторный вход. Админу: dbrain login.",
    "timeout": "⌛ Превышено время ожидания ответа. Попробуй ещё раз.",
    "error": "❌ Ошибка сессии. Попробуй позже.",
}


class ChatSessionManager:
    """Routes chat messages to the shared interactive session."""

    def __init__(
        self,
        vault_path: Path | str,
        session: Any | None = None,
    ) -> None:
        self.vault_path = Path(vault_path)
        self._session = session if session is not None else get_session(get_settings())

    async def send_message(self, user_id: int, prompt: str) -> str:
        """Send a message to the session and return the reply text.

        Serialized via the process-wide ask-lock; runs the blocking ask() in a
        worker thread so the event loop stays responsive.
        """
        async with get_ask_lock():
            res = await asyncio.to_thread(self._session.ask, prompt)
        if res.ok:
            return res.reply or ""
        logger.warning("session ask for user %d returned %s", user_id, res.status)
        return _STATUS_MESSAGES.get(res.status, _STATUS_MESSAGES["error"])

    def reset(self, user_id: int) -> None:
        """Clear the live session context (durable data in files is kept)."""
        self._session.clear()
        logger.info("session cleared (reset) requested by user %d", user_id)

    async def compact(self, user_id: int) -> str:
        """Durable-state-first: clearing is the compaction; memory lives in
        files, so there is nothing to summarize into the session."""
        self._session.clear()
        return "🧹 Сессия очищена (важные данные сохранены в файлах)."
