from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards import CB_CANCEL, CB_MAIN, CB_NOOP, main_menu

router = Router(name="common")

TXT_MAIN = (
    "🎛 <b>Utub-TikTok — панель</b>\n\n"
    "Слежу за TikTok-аккаунтами, при появлении нового видео скачиваю и заливаю на "
    "выбранный YouTube-канал. Управление — через меню ниже."
)


async def _show_main(update: Message | CallbackQuery) -> None:
    if isinstance(update, CallbackQuery):
        with suppress(TelegramBadRequest):
            await update.message.edit_text(TXT_MAIN, reply_markup=main_menu())
        await update.answer()
    else:
        await update.answer(TXT_MAIN, reply_markup=main_menu())


@router.message(CommandStart(), StateFilter("*"))
@router.message(Command("menu", "admin"), StateFilter("*"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _show_main(message)


@router.callback_query(F.data == CB_MAIN, StateFilter("*"))
async def cb_main(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _show_main(cq)


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Нет активных диалогов.")
        return
    await state.clear()
    await message.answer("✖️ Действие отменено.")
    await _show_main(message)


@router.callback_query(F.data == CB_CANCEL, StateFilter("*"))
async def cb_cancel(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer("Отменено")
    await _show_main(cq)


@router.callback_query(F.data == CB_NOOP, StateFilter("*"))
async def cb_noop(cq: CallbackQuery) -> None:
    await cq.answer()
