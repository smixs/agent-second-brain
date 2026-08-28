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
    "rate_limited": (
        "⏳ Лимит подписки исчерпан. Проверю сам, когда он обновится. "
        "Принудительно: /reset"
    ),
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

    async def send_control(self, text: str) -> None:
        """Fire-and-forget a client-side Claude Code command into the session."""
        async with get_ask_lock():
            await asyncio.to_thread(self._session.send_control, text)

    # ── steering: deliberately NOT under the ask-lock — the lock is held by
    # the in-flight turn these calls are aimed at.

    def is_turn_active(self) -> bool:
        return self._session.is_turn_active()

    def is_steerable_turn(self) -> bool:
        return self._session.is_steerable_turn()

    async def steer(self, text: str) -> None:
        await asyncio.to_thread(self._session.steer, text)

    async def interrupt(self) -> None:
        await asyncio.to_thread(self._session.interrupt)

    async def reset(self, user_id: int) -> str:
        """Clear the live session context (durable data in files is kept).

        Async and off-thread ON PURPOSE: the old sync version ran a blocking
        flock straight on the event loop, so `/new` during a long turn froze
        the entire bot for up to 20 minutes. Now a busy pane just reports
        back and the user can escalate to hard_reset().
        """
        ok = await asyncio.to_thread(self._session.clear)
        logger.info("session clear requested by user %d (ok=%s)", user_id, ok)
        if ok:
            return "🧹 Контекст сессии очищен. Файлы vault не тронуты."
        return (
            "⚠️ Сессия занята — контекст не очищен. "
            "Жёсткий сброс: /reset"
        )

    async def hard_reset(self, user_id: int) -> str:
        """Recreate the session no matter what — the /reset escape hatch.

        Never waits on the pane lock, so it works precisely when the session
        is wedged, a turn is stuck, or a stale rate-limit record is blocking
        every request.
        """
        clean = await asyncio.to_thread(self._session.hard_reset)
        logger.warning("hard reset requested by user %d (clean=%s)", user_id, clean)
        if clean:
            return "♻️ Сессия пересоздана. Контекст чистый, лимиты сброшены."
        return (
            "♻️ Сессия пересоздана, зависший запрос прерван. "
            "Контекст чистый, лимиты сброшены."
        )

    async def compact(self, user_id: int) -> str:
        """Durable-state-first: clearing is the compaction; memory lives in
        files, so there is nothing to summarize into the session."""
        return await self.reset(user_id)
