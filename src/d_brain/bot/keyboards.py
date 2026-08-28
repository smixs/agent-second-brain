"""Reply keyboards for Telegram bot."""

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Main reply keyboard.

    Reset is on the keyboard on purpose: it is needed exactly when the bot
    stops answering, and hunting for a slash command on a phone at that
    moment is the worst possible UX.
    """
    builder = ReplyKeyboardBuilder()
    builder.button(text="📊 Статус")
    builder.button(text="⚙️ Обработать")
    builder.button(text="♻️ Сброс")
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
