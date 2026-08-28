"""Telegram bot initialization and polling.

Everything long-running in the process (polling, the cron ticker, the
session watchdog, the systemd ping) is SUPERVISED: a crash is logged and the
loop restarts with a backoff. Nothing here may exit the process on a
transient failure, and nothing may block the event loop.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent, Update

from d_brain.config import Settings
from d_brain.services.cron_runner import run_cron
from d_brain.services.runtime import get_session
from d_brain.services.systemd_notify import notify, watchdog_interval
from d_brain.services.watchdog import run_watchdog

logger = logging.getLogger(__name__)

BACKOFF_MIN = 5.0
BACKOFF_MAX = 300.0


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
    """Ping systemd's watchdog while the event loop is healthy.

    Only meaningful with Type=notify + WatchdogSec= in the unit (see
    deploy/brain.service): systemd then restarts the bot when this stops —
    the one mechanism that catches a FROZEN event loop, as opposed to a
    crashed process.
    """
    interval = watchdog_interval()
    while True:
        await asyncio.sleep(interval)
        notify("WATCHDOG=1")


def supervise(name: str, factory: Callable[[], Awaitable[Any]]) -> asyncio.Task:
    """Run a background coroutine forever, restarting it if it dies.

    Bare create_task() hides failures: a background loop that raised on its
    first line stayed dead for the whole uptime, and the traceback only
    surfaced at GC as "Task exception was never retrieved". Here every crash
    is logged and the loop comes back with a backoff.
    """

    async def runner() -> None:
        delay = BACKOFF_MIN
        while True:
            try:
                await factory()
                logger.warning("background task %s returned; restarting", name)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("background task %s crashed; restart in %.0fs",
                                 name, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX)

    return asyncio.create_task(runner(), name=name)


def register_error_handler(dp: Dispatcher) -> None:
    """Log any unhandled handler exception and tell the user something broke.

    Without this an exception inside a handler is swallowed by aiogram and
    the chat just goes silent — indistinguishable from a hung brain.
    """

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        # exc_info explicitly: this runs as a callback, so the ambient
        # sys.exc_info() logger.exception() relies on is not guaranteed.
        logger.error("handler failed", exc_info=event.exception)
        message = getattr(event.update, "message", None)
        if message is not None:
            with contextlib.suppress(Exception):
                await message.answer(
                    "❌ Внутренняя ошибка. Записал в лог. "
                    "Если повторится — /reset"
                )
        return True  # handled: never let it bubble into the polling loop


async def _polling_loop(bot: Bot, dp: Dispatcher) -> None:
    """Poll Telegram, surviving transient API/network failures.

    aiogram retries ordinary network errors internally, but a fatal one
    (conflicting instance, revoked token, DNS outage) propagates and used to
    END the process. Under systemd that meant a restart every time; under
    any other supervisor it meant a dead bot.
    """
    delay = BACKOFF_MIN
    while True:
        try:
            await dp.start_polling(
                bot, allowed_updates=dp.resolve_used_update_types()
            )
            logger.warning("polling stopped cleanly; restarting")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("polling failed; retry in %.0fs", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX)
            continue
        delay = BACKOFF_MIN
        await asyncio.sleep(BACKOFF_MIN)


async def run_bot(settings: Settings) -> None:
    """Run the bot: polling plus the supervised background loops."""
    bot = create_bot(settings)
    dp = create_dispatcher()

    # Always add auth middleware for security (it handles allow_all_users internally)
    dp.update.middleware(create_auth_middleware(settings))
    register_error_handler(dp)

    # Bring the persistent Claude session up before serving requests; failure
    # here is non-fatal (ask() will retry ensure on demand).
    try:
        await asyncio.to_thread(get_session(settings).ensure_session)
    except Exception:
        logger.exception("Claude session failed to start at boot; retrying on demand")

    notify("READY=1")
    tasks = [supervise("watchdog-ping", _watchdog_pinger)]
    if settings.watchdog_enabled:
        # In-process (one service, one python) — systemd restarts the bot if
        # the loop itself freezes, and this loop recovers the tmux brain.
        tasks.append(supervise("session-watchdog", lambda: run_watchdog(settings, bot)))
    if settings.cron_enabled:
        tasks.append(supervise("cron", lambda: run_cron(settings, bot)))

    logger.info("Starting bot polling...")
    try:
        await _polling_loop(bot, dp)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bot.session.close()
