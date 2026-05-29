"""CRUD YouTube-каналов + per-channel OAuth-флоу.

Add-FSM: title → выбор источника client_secrets → (загрузка docs) → OAuth в браузере.
"""
import asyncio
import logging
from contextlib import suppress
from html import escape
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from config import Settings
from keyboards import (
    CB_CANCEL, CB_MAIN, CB_YT, CB_YT_ADD, CB_YT_DEL, CB_YT_LIST_P, CB_YT_REAUTH,
    CB_YT_S_HELP, CB_YT_S_UPLOAD, CB_YT_S_USE_SHARED,
    back_to, cancel_kb, paginated, pick_secrets_method_kb, youtube_menu,
)
from services import youtube_auth
from services.quota import quota_for_channel
from services.storage import Storage, YouTubeChannel
from states import AddYouTube

log = logging.getLogger("utub.handlers.yt")
router = Router(name="youtube")

YT_SECRETS_GUIDE = (
    "📺 <b>Как получить client_secrets.json</b>\n\n"
    "Файл = OAuth-учётки Google Cloud-проекта, через который бот зальёт видео на твой канал.\n\n"
    "<b>Шаги:</b>\n"
    "1. <code>https://console.cloud.google.com/</code> → <b>Create Project</b> "
    "(имя любое, например <i>cooking-uploader</i>).\n"
    "2. <b>APIs &amp; Services → Library</b> → найди <b>YouTube Data API v3</b> → <b>Enable</b>.\n"
    "3. <b>APIs &amp; Services → OAuth consent screen</b>:\n"
    "   • User Type: <b>External</b>;\n"
    "   • App name + Support email — заполни;\n"
    "   • <b>Test users</b> — добавь Google-аккаунт, к которому привязан твой YouTube-канал. "
    "Без этого Google форсит <code>privacyStatus=private</code>.\n"
    "4. <b>APIs &amp; Services → Credentials → Create credentials → OAuth client ID</b>:\n"
    "   • Application type: <b>Desktop app</b>;\n"
    "   • Name: любое.\n"
    "5. Нажми ⬇️ <b>Download JSON</b> на созданной записи.\n"
    "6. Пришли этот файл в бота <b>как документ</b> (📎 → Файл).\n\n"
    "<b>Зачем отдельный проект на каждый канал:</b>\n"
    "квота YouTube Data API — 10 000 ед./сутки <i>на проект</i>. 1 аплоад = 1 600 ⇒ "
    "≈6 видео/сутки. С отдельным проектом каждый канал получает свой потолок 6/сутки, "
    "а не делит общий лимит с другими."
)


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


def _run_oauth_sync(tokens_dir: Path, keyring_user: str, client_secrets: Path):
    creds = youtube_auth.get_credentials(tokens_dir, keyring_user, client_secrets)
    return youtube_auth.fetch_my_channel(creds)


@router.callback_query(F.data == CB_YT, StateFilter("*"))
async def cb_yt(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    n = len(storage.list_youtube())
    await _edit(cq, f"📺 <b>YouTube каналы</b>\n\nПодключено: <b>{n}</b>", youtube_menu())


def _row_for(channel: YouTubeChannel, settings: Settings) -> list[InlineKeyboardButton]:
    authed = youtube_auth.has_credentials(settings.secrets_folder / "tokens", channel.keyring_user)
    has_own = youtube_auth.has_client_secrets(settings.secrets_folder, channel.id)
    flag = "🔐" if authed else "⚠️"
    secrets_flag = "🔑" if has_own else "·"
    label = f"{flag}{secrets_flag} {channel.title}"
    return [
        InlineKeyboardButton(text=label[:30], callback_data=f"{CB_YT_REAUTH}{channel.id}"),
        InlineKeyboardButton(text="🗑", callback_data=f"{CB_YT_DEL}{channel.id}"),
    ]


@router.callback_query(F.data.startswith("yt:list:"), StateFilter("*"))
async def cb_yt_list(cq: CallbackQuery, state: FSMContext, storage: Storage,
                    settings: Settings) -> None:
    await state.clear()
    items = storage.list_youtube()
    if not items:
        await _edit(cq, "📺 <b>YouTube каналы</b>\n\nПусто. Подключите канал.",
                    back_to(CB_YT, "← Назад"))
        return
    page = _parse_page(cq.data, CB_YT_LIST_P)
    lines = [
        "📺 <b>YouTube каналы</b>",
        "🔐 авторизован · ⚠️ нет токена · 🔑 отдельный client_secrets · · общий",
        "",
    ]
    for i, c in enumerate(items, start=1):
        uc = c.youtube_channel_id or "—"
        q = quota_for_channel(settings.data_folder, c.id)
        lines.append(
            f"{i}. <b>{escape(c.title)}</b>  <code>{uc}</code>\n"
            f"   квота: {q.used()}/{q.daily_quota} "
            f"(≈{q.remaining() // 1600} аплоадов)"
        )
    kb = paginated(items, page, CB_YT_LIST_P, CB_YT,
                   lambda ch: _row_for(ch, settings))
    await _edit(cq, "\n".join(lines), kb)


@router.callback_query(F.data.startswith(CB_YT_DEL), StateFilter("*"))
async def cb_yt_del(cq: CallbackQuery, state: FSMContext, storage: Storage,
                   settings: Settings) -> None:
    await state.clear()
    ch_id = cq.data[len(CB_YT_DEL):]
    ch = storage.get_youtube(ch_id)
    if ch is not None:
        youtube_auth.clear_credentials(settings.secrets_folder / "tokens", ch.keyring_user)
        youtube_auth.remove_client_secrets(settings.secrets_folder, ch.id)
        quota_file = settings.data_folder / f"quota_{ch.id}.json"
        if quota_file.exists():
            try:
                quota_file.unlink()
            except OSError:
                pass
    if storage.remove_youtube(ch_id):
        await cq.answer(f"Удалён: {ch.title if ch else ch_id}")
    else:
        await cq.answer("Не найден", show_alert=True)
    cq.data = "yt:list:0"
    await cb_yt_list(cq, state, storage, settings)


@router.callback_query(F.data == CB_YT_ADD)
async def cb_yt_add(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddYouTube.waiting_title)
    await _edit(
        cq,
        "📺 <b>Подключение YouTube-канала</b>\n\n"
        "Шаг 1/3. Пришлите короткое имя канала для отображения в боте "
        "(например, <code>Cooking</code>). После добавления и OAuth-флоу настоящее "
        "название канала подтянется автоматически.",
        cancel_kb(),
    )


@router.message(AddYouTube.waiting_title)
async def msg_yt_title(message: Message, state: FSMContext, storage: Storage,
                       settings: Settings) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Пустой ввод. /cancel чтобы отменить.", reply_markup=cancel_kb())
        return

    ch = storage.add_youtube(title)
    await state.update_data(channel_id=ch.id)

    shared = settings.youtube.client_secrets
    has_shared = shared is not None and shared.exists()

    if has_shared:
        await state.set_state(AddYouTube.waiting_method)
        await message.answer(
            f"✅ <b>{escape(ch.title)}</b> создан.\n\n"
            "<b>Шаг 2/3.</b> Откуда взять <code>client_secrets.json</code>?\n\n"
            "🔁 <b>Общий</b> — используем файл, прописанный в <code>.env</code>. "
            "Квота 10 000/сутки делится между всеми каналами на этом файле.\n\n"
            "📤 <b>Отдельный</b> — загружаете свой <code>client_secrets.json</code> "
            "от нового GCP-проекта. Канал получит собственную квоту 10 000/сутки. "
            "<i>Рекомендуется.</i>",
            reply_markup=pick_secrets_method_kb(has_shared=True),
        )
    else:
        await state.set_state(AddYouTube.waiting_secrets)
        await message.answer(
            f"✅ <b>{escape(ch.title)}</b> создан.\n\n"
            "<b>Шаг 2/3.</b> Пришлите <code>client_secrets.json</code> "
            "от OAuth Desktop-клиента (📎 → Файл).\n\n"
            "Нет файла — нажмите гайд ниже.",
            reply_markup=pick_secrets_method_kb(has_shared=False),
        )


@router.callback_query(F.data == CB_YT_S_HELP, StateFilter("*"))
async def cb_yt_secrets_help(cq: CallbackQuery, state: FSMContext) -> None:
    # state НЕ чистим — пользователь читает гайд внутри потока добавления
    await cq.message.answer(YT_SECRETS_GUIDE)
    await cq.answer()


@router.callback_query(F.data == CB_YT_S_USE_SHARED, AddYouTube.waiting_method)
async def cb_yt_secrets_shared(cq: CallbackQuery, state: FSMContext, storage: Storage,
                              settings: Settings) -> None:
    data = await state.get_data()
    ch = storage.get_youtube(data.get("channel_id") or "")
    if ch is None:
        await cq.answer("Сессия потерялась — начните заново", show_alert=True)
        await state.clear()
        return
    shared = settings.youtube.client_secrets
    if not shared or not shared.exists():
        await cq.answer("Общий файл недоступен — загрузите отдельный", show_alert=True)
        return
    await cq.message.answer(
        f"⏳ <b>Шаг 3/3.</b> Открываю браузер на хосте для входа в Google-аккаунт <b>{escape(ch.title)}</b>…"
    )
    await cq.answer()
    await _finalize_oauth(cq.message, state, storage, settings, ch, shared, rollback_on_fail=True)


@router.callback_query(F.data == CB_YT_S_UPLOAD, AddYouTube.waiting_method)
async def cb_yt_secrets_upload(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddYouTube.waiting_secrets)
    await _edit(
        cq,
        "📤 <b>Шаг 2/3.</b> Пришлите <code>client_secrets.json</code> в этот чат "
        "<b>как документ</b> (📎 → Файл). Сжатый в фото — не подойдёт.\n\n"
        "Нет файла — гайд ниже.",
        pick_secrets_method_kb(has_shared=False),
    )


@router.message(AddYouTube.waiting_secrets, F.document)
async def msg_yt_secrets_doc(message: Message, state: FSMContext, storage: Storage,
                            settings: Settings, bot: Bot) -> None:
    data = await state.get_data()
    ch = storage.get_youtube(data.get("channel_id") or "")
    if ch is None:
        await message.answer("Сессия потерялась — начните заново.")
        await state.clear()
        return

    doc = message.document
    if doc.file_size and doc.file_size > 100_000:
        await message.answer("Файл слишком большой — это точно client_secrets.json?")
        return

    try:
        buf = await bot.download(doc)
        content = buf.read() if buf else b""
    except Exception as e:
        log.exception("Не удалось скачать документ")
        await message.answer(f"❌ Не смог скачать файл: <code>{escape(str(e))}</code>")
        return

    ok, reason = youtube_auth.validate_client_secrets(content)
    if not ok:
        await message.answer(
            f"❌ Файл невалиден: <i>{escape(reason)}</i>\n\n"
            "Пришлите корректный или /cancel.",
        )
        return

    path = youtube_auth.save_client_secrets(settings.secrets_folder, ch.id, content)
    note = f"\n<i>Замечание: {escape(reason)}</i>" if reason != "OK" else ""
    await message.answer(
        f"✅ client_secrets сохранён для <b>{escape(ch.title)}</b>.{note}\n\n"
        f"⏳ <b>Шаг 3/3.</b> Открываю браузер для входа в Google…",
    )
    await _finalize_oauth(message, state, storage, settings, ch, path, rollback_on_fail=True)


@router.message(AddYouTube.waiting_secrets)
async def msg_yt_secrets_not_doc(message: Message) -> None:
    await message.answer(
        "Пришлите <code>client_secrets.json</code> именно как <b>документ</b> "
        "(📎 → Файл). Текст или фото не подойдут. /cancel — отмена.",
    )


async def _finalize_oauth(reply_target: Message, state: FSMContext, storage: Storage,
                         settings: Settings, ch: YouTubeChannel, client_secrets: Path,
                         *, rollback_on_fail: bool) -> None:
    tokens_dir = settings.secrets_folder / "tokens"
    try:
        result = await asyncio.to_thread(
            _run_oauth_sync, tokens_dir, ch.keyring_user, client_secrets,
        )
    except Exception as e:
        log.exception("OAuth flow упал")
        if rollback_on_fail:
            storage.remove_youtube(ch.id)
            youtube_auth.remove_client_secrets(settings.secrets_folder, ch.id)
        await reply_target.answer(
            f"❌ Не удалось авторизоваться: <code>{escape(str(e))}</code>",
            reply_markup=back_to(CB_YT, "← К YouTube"),
        )
        await state.clear()
        return

    if result is None:
        if rollback_on_fail:
            storage.remove_youtube(ch.id)
            youtube_auth.remove_client_secrets(settings.secrets_folder, ch.id)
        await reply_target.answer(
            "❌ У этого Google-аккаунта нет YouTube-канала. "
            "Создайте канал в YouTube Studio и попробуйте снова.",
            reply_markup=back_to(CB_YT, "← К YouTube"),
        )
        await state.clear()
        return

    yt_channel_id, real_title = result
    storage.update_youtube_meta(ch.id, title=real_title, youtube_channel_id=yt_channel_id)
    await reply_target.answer(
        f"✅ Канал подключён!\n\n"
        f"<b>{escape(real_title)}</b>\n<code>{yt_channel_id}</code>\n\n"
        f"Своя квота 10 000/сутки (≈6 аплоадов). Создавайте пару в 🔗 Пары.",
        reply_markup=back_to(CB_MAIN, "🏠 Главное"),
    )
    await state.clear()


@router.callback_query(F.data.startswith(CB_YT_REAUTH), StateFilter("*"))
async def cb_yt_reauth(cq: CallbackQuery, state: FSMContext, storage: Storage,
                     settings: Settings) -> None:
    await state.clear()
    ch_id = cq.data[len(CB_YT_REAUTH):]
    ch = storage.get_youtube(ch_id)
    if ch is None:
        await cq.answer("Не найден", show_alert=True)
        return

    tokens_dir = settings.secrets_folder / "tokens"
    if youtube_auth.has_credentials(tokens_dir, ch.keyring_user):
        await cq.answer(f"Уже авторизован: {ch.title}")
        return

    try:
        client_secrets = youtube_auth.resolve_client_secrets(
            settings.secrets_folder, ch.id, settings.youtube.client_secrets,
        )
    except youtube_auth.AuthError:
        await state.set_state(AddYouTube.waiting_secrets)
        await state.update_data(channel_id=ch.id)
        await cq.message.answer(
            f"📤 Для <b>{escape(ch.title)}</b> нет client_secrets — пришлите файл "
            "как документ (📎). Гайд — кнопкой.",
            reply_markup=pick_secrets_method_kb(has_shared=False),
        )
        await cq.answer()
        return

    await cq.message.answer(
        f"⏳ Открываю браузер для авторизации <b>{escape(ch.title)}</b>…",
    )
    await cq.answer()
    await _finalize_oauth(cq.message, state, storage, settings, ch, client_secrets,
                          rollback_on_fail=False)
