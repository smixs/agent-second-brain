"""Button handlers for the reply keyboard — thin aliases for the commands."""

from aiogram import F, Router
from aiogram.types import Message

router = Router(name="buttons")


@router.message(F.text == "📊 Статус")
async def btn_status(message: Message) -> None:
    from d_brain.bot.handlers.commands import cmd_status

    await cmd_status(message)


@router.message(F.text == "⚙️ Обработать")
async def btn_process(message: Message) -> None:
    from d_brain.bot.handlers.process import cmd_process

    await cmd_process(message)


@router.message(F.text == "♻️ Сброс")
async def btn_reset(message: Message) -> None:
    from d_brain.bot.handlers.commands import cmd_reset

    await cmd_reset(message)
