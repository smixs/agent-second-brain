"""Command handlers for /start, /help, /status, /new, /reset."""

import asyncio
import html
import logging
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from d_brain.bot.keyboards import get_main_keyboard
from d_brain.config import get_settings
from d_brain.services.chat_session import ChatSessionManager
from d_brain.services.session import SessionStore
from d_brain.services.storage import VaultStorage

router = Router(name="commands")
logger = logging.getLogger(__name__)

# A hard reset kills and rebuilds a tmux session; the startup handshake is
# capped at 90s inside ClaudeSession, so this is that plus slack.
RESET_TIMEOUT = 120.0


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    await message.answer(
        "<b>Второй мозг</b>\n\n"
        "Голос, текст, фото, файлы, пересланные — принимаю всё, "
        "структурирую и кладу в vault.\n\n"
        "<b>Команды</b>\n"
        "/status — записи за день и состояние сессии\n"
        "/process — обработать записи дня\n"
        "/new — очистить контекст\n"
        "/reset — жёсткий сброс зависшей сессии\n"
        "/help — справка",
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    await message.answer(
        "<b>Второй мозг</b>\n\n"
        "🎤 Голосовое — транскрибирую и обработаю\n"
        "💬 Текст — обработаю как есть\n"
        "📎 Фото и файлы — прочитаю и сохраню суть\n\n"
        "<b>Команды</b>\n"
        "/status — записи за день и состояние сессии\n"
        "/process — обработать записи дня\n"
        "/new — очистить контекст (файлы vault не трогаю)\n"
        "/reset — жёсткий сброс: пересоздать сессию, снять "
        "зависший запрос и залипший лимит\n\n"
        "Если ответ не приходит — <code>/reset</code>. "
        "Если и это не помогло — на сервере <code>dbrain repair</code>."
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Handle /status command."""
    user_id = message.from_user.id if message.from_user else 0
    settings = get_settings()
    storage = VaultStorage(settings.vault_path)

    # Log command
    session = SessionStore(settings.vault_path)
    session.append(user_id, "command", cmd="/status")

    today = date.today()
    content = storage.read_daily(today)

    if not content:
        await message.answer(f"📅 <b>{today}</b>\n\nЗаписей пока нет.")
        return

    lines = content.strip().split("\n")
    entries = [line for line in lines if line.startswith("## ")]

    voice_count = sum(1 for e in entries if "[voice]" in e)
    text_count = sum(1 for e in entries if "[text]" in e)
    photo_count = sum(1 for e in entries if "[photo]" in e)
    forward_count = sum(1 for e in entries if "[forward]" in e)

    total = len(entries)

    # Get weekly stats from session
    week_stats = ""
    stats = session.get_stats(user_id, days=7)
    if stats:
        week_stats = "\n\n<b>За 7 дней:</b>"
        for entry_type, count in sorted(stats.items()):
            week_stats += f"\n• {entry_type}: {count}"

    await message.answer(
        f"📅 <b>{today}</b>\n\n"
        f"Всего записей: <b>{total}</b>\n"
        f"- 🎤 Голосовых: {voice_count}\n"
        f"- 💬 Текстовых: {text_count}\n"
        f"- 📷 Фото: {photo_count}\n"
        f"- ↩️ Пересланных: {forward_count}"
        f"{week_stats}"
        f"{_session_line(settings)}"
    )


def _session_line(settings) -> str:
    """One line on session health — the limit window is the thing the user
    most often needs to see, and it used to be invisible from Telegram."""
    from d_brain.services.runtime import get_session

    try:
        session = get_session(settings)
        rec, holding = session.rate_limit_status()
    except Exception:  # noqa: BLE001 — /status must never fail on diagnostics
        logger.exception("could not read session state for /status")
        return ""
    if rec is not None and holding:
        return (
            "\n\n⏳ <b>Лимит исчерпан</b>, следующая попытка после "
            f"<code>{rec.until.strftime('%H:%M')}</code>. Сбросить: /reset"
        )
    if session.is_turn_active():
        return "\n\n⚙️ Сейчас выполняется запрос."
    return "\n\n🟢 Сессия свободна."


@router.message(Command("new", "compact", "clear"))
async def cmd_new(message: Message) -> None:
    """Soft reset: drop the live context, keep the session process."""
    if not message.from_user:
        return

    settings = get_settings()
    manager = ChatSessionManager(settings.vault_path)
    await message.answer(await manager.reset(message.from_user.id))


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    """Hard reset — the escape hatch for a wedged brain.

    Deliberately takes no lock and waits for nothing: it exists for the case
    where a turn is stuck, the pane is wedged, or an expired rate-limit
    record still blocks every request. Bounded by a timeout so the handler
    itself can never become the thing that hangs.
    """
    if not message.from_user:
        return

    settings = get_settings()
    manager = ChatSessionManager(settings.vault_path)
    await message.answer("♻️ Пересоздаю сессию…")
    try:
        result = await asyncio.wait_for(
            manager.hard_reset(message.from_user.id), timeout=RESET_TIMEOUT
        )
    except TimeoutError:
        logger.error("hard reset timed out after %ss", RESET_TIMEOUT)
        result = (
            "⚠️ Сброс не уложился в "
            f"{RESET_TIMEOUT:.0f} c. На сервере: <code>dbrain repair</code>"
        )
    except Exception as exc:  # noqa: BLE001 — the recovery path must not 500
        logger.exception("hard reset failed")
        result = f"❌ Сброс не удался: <code>{html.escape(str(exc)[:200])}</code>"
    await message.answer(result)
