"""Review: карточка админу + Approve/Edit/Skip."""
from __future__ import annotations

import logging
from contextlib import suppress
from html import escape
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from config import Settings
from keyboards import (
    CB_RV_APPROVE, CB_RV_EDIT, CB_RV_SKIP, review_card_kb,
)
from services.db import Database, S_READY, S_SKIPPED
from services.storage import Storage
from states import EditReviewTitle

log = logging.getLogger("utub.handlers.review")
router = Router(name="review")


async def send_review_card(bot: Bot, db: Database, storage: Storage,
                           settings: Settings, video_id: int) -> None:
    """Карточку получает первый админ из ADMIN_USERS."""
    admin = settings.primary_admin
    if admin is None:
        log.warning("ADMIN_USERS пуст — review-карточку слать некому")
        return
    video = db.get(video_id)
    if video is None or not video.local_path:
        return
    caption = _build_caption(video, storage)
    try:
        file = FSInputFile(video.local_path)
        msg = await bot.send_video(
            chat_id=admin,
            video=file,
            caption=caption,
            supports_streaming=True,
            reply_markup=review_card_kb(video.id),
        )
        db.update(video.id, review_chat_id=admin, review_message_id=msg.message_id)
    except TelegramAPIError as e:
        # Видео тяжёлое или формат не принят — fallback документом.
        log.warning("send_video не прошёл (%s), пробую send_document", e)
        try:
            file = FSInputFile(video.local_path)
            msg = await bot.send_document(
                chat_id=admin,
                document=file,
                caption=caption,
                reply_markup=review_card_kb(video.id),
            )
            db.update(video.id, review_chat_id=admin, review_message_id=msg.message_id)
        except TelegramAPIError as e2:
            log.error("send_document тоже упал: %s — шлю только текст", e2)
            msg = await bot.send_message(
                admin,
                f"{caption}\n\n⚠️ Не удалось приложить файл: {escape(str(e2))[:200]}",
                reply_markup=review_card_kb(video.id),
            )
            db.update(video.id, review_chat_id=admin, review_message_id=msg.message_id)


def _build_caption(video, storage: Storage) -> str:
    pair = storage.get_pair(video.pair_id)
    tt = storage.get_tiktok(video.tiktok_account_id) if pair else None
    yt = storage.get_youtube(pair.youtube_channel_id) if pair else None
    tt_label = f"@{tt.username}" if tt else "?"
    yt_label = yt.title if yt else "?"
    title = (video.title or "").strip() or "(без названия)"
    desc = (video.description or "").strip()
    head = (
        f"📥 <b>На review</b> · #{video.id}\n"
        f"<b>{escape(tt_label)}</b> → <b>{escape(yt_label)}</b>\n\n"
        f"<b>Заголовок (зальётся такой):</b>\n{escape(title)[:200]}"
    )
    if desc and desc != title:
        head += f"\n\n<b>Описание:</b>\n{escape(desc)[:400]}"
    # Telegram caption ≤ 1024 символа
    return head[:1024]


def _vid_from(cq: CallbackQuery, prefix: str) -> int | None:
    try:
        return int(cq.data[len(prefix):])
    except (TypeError, ValueError):
        return None


async def _replace_keyboard_with_text(cq: CallbackQuery, suffix: str) -> None:
    """Снять кнопки и дописать итог в caption."""
    msg: Message = cq.message  # type: ignore[assignment]
    base = msg.caption or msg.text or ""
    new = (base + "\n\n" + suffix)[:1024]
    with suppress(TelegramBadRequest):
        if msg.caption is not None:
            await msg.edit_caption(caption=new, reply_markup=None)
        else:
            await msg.edit_text(new, reply_markup=None)


@router.callback_query(F.data.startswith(CB_RV_APPROVE), StateFilter("*"))
async def cb_rv_approve(cq: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    vid = _vid_from(cq, CB_RV_APPROVE)
    if vid is None:
        await cq.answer("Bad id", show_alert=True)
        return
    v = db.get(vid)
    if v is None:
        await cq.answer("Не найдено", show_alert=True)
        return
    db.update(vid, status=S_READY)
    await cq.answer("✅ Поставил в очередь на YouTube")
    await _replace_keyboard_with_text(cq, "✅ <b>Approved</b> — поставлено в очередь на YouTube.")


@router.callback_query(F.data.startswith(CB_RV_SKIP), StateFilter("*"))
async def cb_rv_skip(cq: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    vid = _vid_from(cq, CB_RV_SKIP)
    if vid is None:
        await cq.answer("Bad id", show_alert=True)
        return
    v = db.get(vid)
    if v is None:
        await cq.answer("Не найдено", show_alert=True)
        return
    db.update(vid, status=S_SKIPPED)
    if v.local_path:
        try:
            Path(v.local_path).unlink(missing_ok=True)
        except OSError:
            pass
    await cq.answer("❌ Пропущено")
    await _replace_keyboard_with_text(cq, "❌ <b>Skipped</b> — пропущено, файл удалён.")


@router.callback_query(F.data.startswith(CB_RV_EDIT), StateFilter("*"))
async def cb_rv_edit(cq: CallbackQuery, state: FSMContext, db: Database) -> None:
    vid = _vid_from(cq, CB_RV_EDIT)
    if vid is None:
        await cq.answer("Bad id", show_alert=True)
        return
    v = db.get(vid)
    if v is None:
        await cq.answer("Не найдено", show_alert=True)
        return
    await state.set_state(EditReviewTitle.waiting_input)
    await state.update_data(video_id=vid)
    current = (v.title or "").strip() or "(пусто)"
    await cq.message.answer(
        f"✏️ <b>Новый заголовок для #{vid}</b>\n\n"
        f"Текущий: <code>{escape(current)[:200]}</code>\n\n"
        f"Пришлите новый текст одним сообщением или /cancel.",
    )
    await cq.answer()


@router.message(EditReviewTitle.waiting_input)
async def msg_edit_title(message: Message, state: FSMContext, db: Database,
                         bot: Bot, storage: Storage, settings: Settings) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пустой текст. /cancel чтобы отменить.")
        return
    data = await state.get_data()
    vid = data.get("video_id")
    if not isinstance(vid, int):
        await message.answer("Сессия потерялась.")
        await state.clear()
        return
    db.update(vid, title=text)
    await state.clear()
    await message.answer(f"✅ Заголовок обновлён. Заново перешлю карточку:")
    await send_review_card(bot, db, storage, settings, vid)
