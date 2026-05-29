"""/status, очередь, справка."""
from contextlib import suppress
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Settings
from keyboards import CB_HELP, CB_MAIN, CB_QUEUE, CB_Q_DEL, CB_Q_RETRY, back_to
from services.db import Database, S_DONE, S_FAILED, S_READY
from services.quota import quota_for_channel
from services.storage import Storage

router = Router(name="info")

HELP = (
    "ℹ️ <b>Как это работает</b>\n\n"
    "1. <b>🎵 TikTok аккаунты</b> — добавьте @username, бот раз в N секунд проверяет их через yt-dlp.\n"
    "2. <b>📺 YouTube каналы</b> — подключите каждый канал: имя → client_secrets.json → OAuth в браузере на хосте.\n"
    "3. <b>🔗 Пары</b> — TikTok → YouTube. Можно несколько ⇒ один TikTok льётся в несколько YouTube, и наоборот.\n"
    "4. <b>Режимы</b>:\n"
    "   • 📝 <b>Review</b> — карточка в ЛС, заливаем только после ✅.\n"
    "   • ⚡ <b>Auto</b> — скачали и сразу залили.\n"
    "5. <b>📊 Очередь</b> — что сейчас обрабатывается, что упало, что готово.\n\n"
    "<b>Лимит YouTube API</b>: 10 000 единиц/сутки <i>на каждый GCP-проект</i> "
    "(= один <code>client_secrets.json</code>). Аплоад = 1 600 ⇒ ≈6 видео/сутки на проект. "
    "У каждого канала может быть свой проект — тогда квоты независимые."
)


async def _edit(cq: CallbackQuery, text: str, kb) -> None:
    with suppress(TelegramBadRequest):
        await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()


@router.callback_query(F.data == CB_HELP, StateFilter("*"))
async def cb_help(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit(cq, HELP, back_to(CB_MAIN, "🏠 Главное"))


def _quota_lines(storage: Storage, settings: Settings) -> list[str]:
    channels = storage.list_youtube()
    if not channels:
        return ["<b>YouTube квоты:</b> каналов нет"]
    out = ["<b>YouTube квоты:</b>"]
    for c in channels:
        q = quota_for_channel(settings.data_folder, c.id)
        out.append(
            f"  • {escape(c.title)}: {q.used()}/{q.daily_quota} "
            f"(≈{q.remaining() // 1600} аплоадов)"
        )
    return out


def _format_status(header: str, storage: Storage, db: Database, settings: Settings) -> str:
    stats = db.stats()
    parts = [
        header,
        "",
        f"🎵 TikTok: <b>{len(storage.list_tiktok())}</b>, "
        f"📺 YouTube: <b>{len(storage.list_youtube())}</b>, "
        f"🔗 пар: <b>{len(storage.list_pairs())}</b>",
        "",
        "<b>Очередь:</b>",
    ]
    if not stats:
        parts.append("  пусто")
    else:
        for k, v in stats.items():
            parts.append(f"  {k}: <b>{v}</b>")
    parts.append("")
    parts.extend(_quota_lines(storage, settings))
    return "\n".join(parts)


@router.message(Command("status"))
async def cmd_status(message: Message, storage: Storage, db: Database,
                     settings: Settings) -> None:
    await message.answer(_format_status("📊 <b>Статус</b>", storage, db, settings))


@router.callback_query(F.data == CB_QUEUE, StateFilter("*"))
async def cb_queue(cq: CallbackQuery, state: FSMContext, storage: Storage, db: Database,
                  settings: Settings) -> None:
    await state.clear()
    recent = db.list_recent(limit=10)
    text = _format_status("📊 <b>Статус и очередь</b>", storage, db, settings)
    if recent:
        text += "\n\n<b>Последние записи:</b>"
        for v in recent:
            tt = storage.get_tiktok(v.tiktok_account_id)
            who = f"@{tt.username}" if tt else "?"
            line = f"\n• #{v.id} {v.status} · {who} · <code>{v.tiktok_video_id}</code>"
            if v.status in (S_FAILED, S_READY) and v.last_error:
                line += f"\n   ⚠️ {v.last_error[:200]}"
            if v.status == S_DONE and v.youtube_video_id:
                line += f"\n   ▶️ https://youtu.be/{v.youtube_video_id}"
            text += line
    rows: list[list[InlineKeyboardButton]] = []
    for v in recent:
        if v.status == S_FAILED:
            rows.append([
                InlineKeyboardButton(text=f"↻ Retry #{v.id}", callback_data=f"{CB_Q_RETRY}{v.id}"),
                InlineKeyboardButton(text="🗑", callback_data=f"{CB_Q_DEL}{v.id}"),
            ])
    rows.append([InlineKeyboardButton(text="🏠 Главное", callback_data=CB_MAIN)])
    await _edit(cq, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith(CB_Q_RETRY), StateFilter("*"))
async def cb_q_retry(cq: CallbackQuery, state: FSMContext, storage: Storage, db: Database,
                     settings: Settings) -> None:
    await state.clear()
    try:
        vid = int(cq.data[len(CB_Q_RETRY):])
    except ValueError:
        await cq.answer("Bad id", show_alert=True)
        return
    if db.retry(vid):
        await cq.answer(f"#{vid} → DISCOVERED, попробую снова")
    else:
        await cq.answer("Можно ретраить только FAILED", show_alert=True)
    cq.data = CB_QUEUE
    await cb_queue(cq, state, storage, db, settings)


@router.callback_query(F.data.startswith(CB_Q_DEL), StateFilter("*"))
async def cb_q_del(cq: CallbackQuery, state: FSMContext, storage: Storage, db: Database,
                  settings: Settings) -> None:
    await state.clear()
    try:
        vid = int(cq.data[len(CB_Q_DEL):])
    except ValueError:
        await cq.answer("Bad id", show_alert=True)
        return
    if db.delete(vid):
        await cq.answer(f"#{vid} удалён")
    else:
        await cq.answer("Не найден", show_alert=True)
    cq.data = CB_QUEUE
    await cb_queue(cq, state, storage, db, settings)
