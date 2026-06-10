"""Telegram bot initialization and polling."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update

from d_brain.config import Settings
from d_brain.services.runtime import get_session
from d_brain.services.systemd_notify import notify, watchdog_interval

logger = logging.getLogger(__name__)


def create_bot(settings: Settings) -> Bot:
    """Create and configure the Telegram bot."""
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """Create and configure the dispatcher with routers."""
    from d_brain.bot.handlers import (
        buttons,
        chat,
        commands,
        process,
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Register routers - ORDER MATTERS
    dp.include_router(commands.router)
    dp.include_router(process.router)
    dp.include_router(buttons.router)  # Reply keyboard buttons
    dp.include_router(chat.router)  # Catch-all for private chat (LAST)
    return dp


MiddlewareHandler = Callable[[Update, dict[str, Any]], Awaitable[Any]]
MiddlewareType = Callable[[MiddlewareHandler, Update, dict[str, Any]], Awaitable[Any]]


def create_auth_middleware(settings: Settings) -> MiddlewareType:
    """Create middleware to check user authorization."""

    async def auth_middleware(
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        # If explicitly allowed all users, just bypass check
        if settings.allow_all_users:
            return await handler(event, data)

        user = None
        if event.message:
            user = event.message.from_user
        elif event.callback_query:
            user = event.callback_query.from_user

        # If no users allowed and not allow_all_users -> deny everyone
        if not settings.allowed_user_ids:
            logger.warning(
                "Access denied: no allowed_user_ids configured and "
                "allow_all_users is False"
            )
            return None

        # Check if user is in allowed list
        if user and user.id not in settings.allowed_user_ids:
            logger.warning("Unauthorized access attempt from user %s", user.id)
            return None

        return await handler(event, data)

    return auth_middleware


async def _watchdog_pinger() -> None:
    """Ping systemd's watchdog while the event loop is healthy."""
    interval = watchdog_interval()
    while True:
        await asyncio.sleep(interval)
        notify("WATCHDOG=1")


async def run_bot(settings: Settings) -> None:
    """Run the bot with polling."""
    bot = create_bot(settings)
    dp = create_dispatcher()

    # Always add auth middleware for security (it handles allow_all_users internally)
    dp.update.middleware(create_auth_middleware(settings))

    # Bring the persistent Claude session up before serving requests; failure
    # here is non-fatal (ask() will retry ensure on demand).
    try:
        await asyncio.to_thread(get_session(settings).ensure_session)
    except Exception:
        logger.exception("Claude session failed to start at boot; retrying on demand")

    notify("READY=1")
    pinger = asyncio.create_task(_watchdog_pinger())

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        pinger.cancel()
        await bot.session.close()
