"""CRUD пар TikTok → YouTube. Add-FSM: TikTok → YouTube → mode."""
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from keyboards import (
    CB_CANCEL, CB_MAIN, CB_PR, CB_PR_ADD, CB_PR_DEL, CB_PR_LIST_P,
    CB_PR_MODE, CB_PR_PICK_MODE, CB_PR_PICK_TT, CB_PR_PICK_YT, CB_PR_TOG,
    back_to, cancel_kb, paginated, pairs_menu, pick_mode_kb,
)
from services.storage import Pair, Storage
from states import AddPair

router = Router(name="pairs")


def _parse_page(data: str, prefix: str) -> int:
    if data.startswith(prefix):
        try:
            return int(data[len(prefix):])
        except ValueError:
            pass
    return 0


async def _edit(cq: CallbackQuery, text: str, kb) -> None:
    with suppress(TelegramBadRequest):
        await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()


@router.callback_query(F.data == CB_PR, StateFilter("*"))
async def cb_pr(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    n = len(storage.list_pairs())
    await _edit(cq, f"🔗 <b>Пары TikTok → YouTube</b>\n\nВсего: <b>{n}</b>", pairs_menu())


def _format_pair_line(p: Pair, storage: Storage) -> str:
    tt = storage.get_tiktok(p.tiktok_account_id)
    yt = storage.get_youtube(p.youtube_channel_id)
    tt_label = f"@{tt.username}" if tt else f"<i>удалён {p.tiktok_account_id}</i>"
    yt_label = yt.title if yt else f"<i>удалён {p.youtube_channel_id}</i>"
    state_emoji = "✅" if p.enabled else "⏸"
    mode_emoji = "📝" if p.mode == "review" else "⚡"
    return f"{state_emoji} {mode_emoji} <b>{tt_label}</b> → <b>{yt_label}</b>"


def _row(p: Pair, storage: Storage) -> list[InlineKeyboardButton]:
    tt = storage.get_tiktok(p.tiktok_account_id)
    yt = storage.get_youtube(p.youtube_channel_id)
    short = f"{('@'+tt.username) if tt else '?'}→{yt.title if yt else '?'}"[:24]
    return [
        InlineKeyboardButton(text=("📝" if p.mode == "review" else "⚡") + short,
                             callback_data=f"{CB_PR_MODE}{p.id}"),
        InlineKeyboardButton(text="⏸" if p.enabled else "▶️",
                             callback_data=f"{CB_PR_TOG}{p.id}"),
        InlineKeyboardButton(text="🗑", callback_data=f"{CB_PR_DEL}{p.id}"),
    ]


@router.callback_query(F.data.startswith("pr:list:"), StateFilter("*"))
async def cb_pr_list(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    items = storage.list_pairs()
    if not items:
        await _edit(cq, "🔗 <b>Пары</b>\n\nПусто. Создайте первую пару.",
                    back_to(CB_PR, "← Назад"))
        return
    page = _parse_page(cq.data, CB_PR_LIST_P)
    lines = ["🔗 <b>Пары TikTok → YouTube</b>\n",
             "Первая кнопка — переключить режим (📝 review / ⚡ auto), вторая — пауза, 🗑 — удалить.\n"]
    for i, p in enumerate(items, start=1):
        lines.append(f"{i}. {_format_pair_line(p, storage)}")
    kb = paginated(items, page, CB_PR_LIST_P, CB_PR, lambda p: _row(p, storage))
    await _edit(cq, "\n".join(lines), kb)


@router.callback_query(F.data.startswith(CB_PR_MODE), StateFilter("*"))
async def cb_pr_mode(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    pair_id = cq.data[len(CB_PR_MODE):]
    p = storage.get_pair(pair_id)
    if p is None:
        await cq.answer("Не найдена", show_alert=True)
        return
    new_mode = "auto" if p.mode == "review" else "review"
    storage.set_pair_mode(pair_id, new_mode)
    await cq.answer(f"Режим: {new_mode}")
    cq.data = "pr:list:0"
    await cb_pr_list(cq, state, storage)


@router.callback_query(F.data.startswith(CB_PR_TOG), StateFilter("*"))
async def cb_pr_tog(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    pair_id = cq.data[len(CB_PR_TOG):]
    p = storage.get_pair(pair_id)
    if p is None:
        await cq.answer("Не найдена", show_alert=True)
        return
    storage.set_pair_enabled(pair_id, not p.enabled)
    await cq.answer("Включена" if not p.enabled else "На паузе")
    cq.data = "pr:list:0"
    await cb_pr_list(cq, state, storage)


@router.callback_query(F.data.startswith(CB_PR_DEL), StateFilter("*"))
async def cb_pr_del(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    pair_id = cq.data[len(CB_PR_DEL):]
    if storage.remove_pair(pair_id):
        await cq.answer("Удалена")
    else:
        await cq.answer("Не найдена", show_alert=True)
    cq.data = "pr:list:0"
    await cb_pr_list(cq, state, storage)


def _pick_list(items, prefix: str, label_fn) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append([InlineKeyboardButton(
            text=label_fn(item)[:50],
            callback_data=f"{prefix}{item.id}",
        )])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == CB_PR_ADD)
async def cb_pr_add(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    tts = storage.list_tiktok()
    if not tts:
        await _edit(cq,
                    "🔗 <b>Новая пара</b>\n\nСначала добавьте TikTok-аккаунт в 🎵 TikTok.",
                    back_to(CB_PR, "← Назад"))
        return
    yts = storage.list_youtube()
    if not yts:
        await _edit(cq,
                    "🔗 <b>Новая пара</b>\n\nСначала подключите YouTube-канал в 📺 YouTube.",
                    back_to(CB_PR, "← Назад"))
        return
    await state.set_state(AddPair.pick_tiktok)
    await _edit(cq,
                "🔗 <b>Новая пара</b> · шаг 1/3\n\nВыберите TikTok-аккаунт-источник:",
                _pick_list(tts, CB_PR_PICK_TT, lambda a: f"@{a.username}"))


@router.callback_query(F.data.startswith(CB_PR_PICK_TT), AddPair.pick_tiktok)
async def cb_pr_pick_tt(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    tt_id = cq.data[len(CB_PR_PICK_TT):]
    if storage.get_tiktok(tt_id) is None:
        await cq.answer("Не найден", show_alert=True)
        return
    await state.update_data(tiktok_account_id=tt_id)
    await state.set_state(AddPair.pick_youtube)
    yts = storage.list_youtube()
    await _edit(cq,
                "🔗 <b>Новая пара</b> · шаг 2/3\n\nКуда лить (YouTube-канал)?",
                _pick_list(yts, CB_PR_PICK_YT, lambda c: c.title))


@router.callback_query(F.data.startswith(CB_PR_PICK_YT), AddPair.pick_youtube)
async def cb_pr_pick_yt(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    yt_id = cq.data[len(CB_PR_PICK_YT):]
    if storage.get_youtube(yt_id) is None:
        await cq.answer("Не найден", show_alert=True)
        return
    await state.update_data(youtube_channel_id=yt_id)
    await state.set_state(AddPair.pick_mode)
    await _edit(cq,
                "🔗 <b>Новая пара</b> · шаг 3/3\n\n"
                "Режим работы:\n"
                "• <b>📝 Review</b> — карточка с превью в личку, заливка только после ✅\n"
                "• <b>⚡ Auto</b> — скачали → залили без подтверждения",
                pick_mode_kb())


@router.callback_query(F.data.startswith(CB_PR_PICK_MODE), AddPair.pick_mode)
async def cb_pr_pick_mode(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    mode = cq.data[len(CB_PR_PICK_MODE):]
    if mode not in ("review", "auto"):
        await cq.answer("Что?", show_alert=True)
        return
    data = await state.get_data()
    tt_id = data.get("tiktok_account_id")
    yt_id = data.get("youtube_channel_id")
    if not tt_id or not yt_id:
        await cq.answer("Сессия потерялась — начните заново", show_alert=True)
        await state.clear()
        return
    pair = storage.add_pair(tt_id, yt_id, mode=mode)  # type: ignore[arg-type]
    await state.clear()
    if pair is None:
        await _edit(cq,
                    "ℹ️ Такая пара уже существует.",
                    back_to(CB_PR, "← К парам"))
        return
    await _edit(cq,
                f"✅ Пара создана!\n\n{_format_pair_line(pair, storage)}",
                back_to(CB_MAIN, "🏠 Главное"))
