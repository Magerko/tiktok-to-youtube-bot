"""CRUD TikTok-аккаунтов + cookies per-account."""
import logging
from contextlib import suppress
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from config import Settings
from keyboards import (
    CB_MAIN, CB_TT, CB_TT_ADD, CB_TT_CK, CB_TT_CK_DEL, CB_TT_CK_HELP,
    CB_TT_CK_UP, CB_TT_CKS, CB_TT_DEL, CB_TT_LIST_P, CB_TT_TOG,
    back_to, cancel_kb, cookies_account_screen_kb, paginated, tiktok_menu,
)
from services import cookies
from services.storage import Storage, TikTokAccount
from states import AddTikTok, UploadCookies

log = logging.getLogger("utub.handlers.tt")
router = Router(name="tiktok")

COOKIES_HELP = (
    "🍪 <b>Как получить cookies.txt для TikTok</b>\n\n"
    "Cookies нужны, если yt-dlp возвращает пустой плейлист — обычно из-за региона "
    "или login-wall. Файл вытаскивается из браузера, в котором ты залогинен в TikTok.\n\n"
    "<b>Способ 1 — Chrome / Edge / Brave:</b>\n"
    "1. Поставь расширение «<b>Get cookies.txt LOCALLY</b>» из Chrome Web Store "
    "(автор: <i>cclauss</i>, ~5M пользователей).\n"
    "2. Открой <code>https://www.tiktok.com</code> и убедись, что залогинен.\n"
    "3. Клик по иконке расширения → <b>Export</b> (или <b>Export As → Netscape</b>).\n"
    "4. Скачается файл <code>tiktok.com_cookies.txt</code>.\n\n"
    "<b>Способ 2 — Firefox:</b>\n"
    "1. Поставь расширение «<b>cookies.txt</b>» (автор: <i>Lennon Hill</i>).\n"
    "2. Открой <code>tiktok.com</code>, кликни по иконке расширения → <b>Current Site</b>.\n"
    "3. Сохрани предложенный файл.\n\n"
    "<b>Загрузка в бот:</b> вернись в меню 🍪 Cookies, выбери аккаунт, нажми "
    "<b>📤 Загрузить</b> и пришли файл как документ (не сжимай в фото).\n\n"
    "⚠️ Cookies = логин-сессия. Никому больше не отдавай этот файл."
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


@router.callback_query(F.data == CB_TT, StateFilter("*"))
async def cb_tt(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    n = len(storage.list_tiktok())
    await _edit(cq, f"🎵 <b>TikTok аккаунты</b>\n\nПод наблюдением: <b>{n}</b>", tiktok_menu())


def _row(acc: TikTokAccount) -> list[InlineKeyboardButton]:
    flag = "✅" if acc.enabled else "⏸"
    label = f"{flag} @{acc.username}"
    return [
        InlineKeyboardButton(text=label[:30], callback_data=f"{CB_TT_TOG}{acc.id}"),
        InlineKeyboardButton(text="🗑", callback_data=f"{CB_TT_DEL}{acc.id}"),
    ]


@router.callback_query(F.data.startswith("tt:list:"), StateFilter("*"))
async def cb_tt_list(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    items = storage.list_tiktok()
    if not items:
        await _edit(cq, "🎵 <b>TikTok аккаунты</b>\n\nПусто. Добавьте @username.",
                    back_to(CB_TT, "← Назад"))
        return
    page = _parse_page(cq.data, CB_TT_LIST_P)
    lines = ["🎵 <b>TikTok аккаунты</b>\n",
             "Кнопка с именем — пауза/включить, 🗑 — удалить (и все пары с ним).\n"]
    for i, a in enumerate(items, start=1):
        flag = "✅" if a.enabled else "⏸"
        lines.append(f"{i}. {flag} <b>@{a.username}</b>")
    kb = paginated(items, page, CB_TT_LIST_P, CB_TT, _row)
    await _edit(cq, "\n".join(lines), kb)


@router.callback_query(F.data.startswith(CB_TT_DEL), StateFilter("*"))
async def cb_tt_del(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    acc_id = cq.data[len(CB_TT_DEL):]
    acc = storage.get_tiktok(acc_id)
    if storage.remove_tiktok(acc_id):
        await cq.answer(f"Удалён: @{acc.username if acc else acc_id}")
    else:
        await cq.answer("Не найден", show_alert=True)
    cq.data = "tt:list:0"
    await cb_tt_list(cq, state, storage)


@router.callback_query(F.data.startswith(CB_TT_TOG), StateFilter("*"))
async def cb_tt_tog(cq: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.clear()
    acc_id = cq.data[len(CB_TT_TOG):]
    acc = storage.get_tiktok(acc_id)
    if acc is None:
        await cq.answer("Не найден", show_alert=True)
        return
    storage.set_tiktok_enabled(acc_id, not acc.enabled)
    await cq.answer("Включен" if not acc.enabled else "На паузе")
    cq.data = "tt:list:0"
    await cb_tt_list(cq, state, storage)


@router.callback_query(F.data == CB_TT_ADD)
async def cb_tt_add(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddTikTok.waiting_username)
    await _edit(
        cq,
        "🎵 <b>Добавление TikTok-аккаунта</b>\n\n"
        "Пришлите <b>@username</b> или ссылку <code>https://www.tiktok.com/@username</code>.\n\n"
        "При первом запуске мониторинг просто запомнит самое свежее видео — лить историю не будем. "
        "Новые публикации после этого момента попадут в очередь.",
        cancel_kb(),
    )


@router.message(AddTikTok.waiting_username)
async def msg_tt_add(message: Message, state: FSMContext, storage: Storage) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пустой ввод. /cancel чтобы отменить.", reply_markup=cancel_kb())
        return

    # Парсинг: @user / https://www.tiktok.com/@user / user
    user = text
    if user.startswith("http"):
        # ищем "@..."
        if "/@" in user:
            user = user.split("/@", 1)[1]
        user = user.split("/", 1)[0]
        user = user.split("?", 1)[0]
    user = user.lstrip("@").strip()
    if not user or any(c.isspace() for c in user):
        await message.answer("Не похоже на @username. Пример: <code>@cookingtv</code>",
                             reply_markup=cancel_kb())
        return

    acc = storage.add_tiktok(user)
    if acc is None:
        await message.answer(f"ℹ️ Уже добавлен: <b>@{user}</b>",
                             reply_markup=back_to(CB_TT, "← К TikTok"))
    else:
        await message.answer(
            f"✅ Добавлен: <b>@{acc.username}</b>\n\n"
            f"Не забудьте создать пару TikTok → YouTube в меню 🔗 Пары.",
            reply_markup=back_to(CB_MAIN, "🏠 Главное"),
        )
    await state.clear()


def _cookies_row(acc: TikTokAccount, settings: Settings) -> list[InlineKeyboardButton]:
    flag = "🍪" if cookies.has_cookies(settings.secrets_folder, acc.id) else "—"
    return [InlineKeyboardButton(
        text=f"{flag} @{acc.username}"[:50],
        callback_data=f"{CB_TT_CK}{acc.id}",
    )]


@router.callback_query(F.data == CB_TT_CKS, StateFilter("*"))
async def cb_tt_cookies_list(cq: CallbackQuery, state: FSMContext, storage: Storage,
                            settings: Settings) -> None:
    await state.clear()
    items = storage.list_tiktok()
    if not items:
        await _edit(cq,
                    "🍪 <b>Cookies</b>\n\nСначала добавьте TikTok-аккаунт.",
                    back_to(CB_TT, "← К TikTok"))
        return
    lines = ["🍪 <b>Cookies для TikTok-аккаунтов</b>\n",
             "🍪 — cookies загружены, — — нет. Тапни по аккаунту для управления.\n"]
    for a in items:
        flag = "🍪" if cookies.has_cookies(settings.secrets_folder, a.id) else "—"
        lines.append(f"{flag} <b>@{a.username}</b>")
    rows: list[list[InlineKeyboardButton]] = [_cookies_row(a, settings) for a in items]
    rows.append([InlineKeyboardButton(text="ℹ️ Где их взять", callback_data=CB_TT_CK_HELP)])
    rows.append([InlineKeyboardButton(text="← К TikTok", callback_data=CB_TT)])
    await _edit(cq, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith(CB_TT_CK) & ~F.data.startswith(CB_TT_CK_UP)
                       & ~F.data.startswith(CB_TT_CK_DEL) & (F.data != CB_TT_CK_HELP),
                       StateFilter("*"))
async def cb_tt_cookies_account(cq: CallbackQuery, state: FSMContext, storage: Storage,
                                settings: Settings) -> None:
    await state.clear()
    acc_id = cq.data[len(CB_TT_CK):]
    acc = storage.get_tiktok(acc_id)
    if acc is None:
        await cq.answer("Не найден", show_alert=True)
        return
    has = cookies.has_cookies(settings.secrets_folder, acc_id)
    status_line = "✅ Загружены" if has else "—  не загружены"
    path = cookies.cookies_path(settings.secrets_folder, acc_id) if has else None
    text = (
        f"🍪 <b>Cookies для @{escape(acc.username)}</b>\n\n"
        f"Статус: <b>{status_line}</b>\n"
    )
    if path:
        try:
            size = path.stat().st_size
            text += f"Размер: <b>{size}</b> B\n"
        except OSError:
            pass
    text += (
        "\nЕсли мониторинг для этого аккаунта возвращает пустой список или капчу — "
        "залейте cookies из браузера, где вы залогинены в TikTok."
    )
    await _edit(cq, text, cookies_account_screen_kb(acc_id, has))


@router.callback_query(F.data == CB_TT_CK_HELP, StateFilter("*"))
async def cb_tt_cookies_help(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit(cq, COOKIES_HELP, back_to(CB_TT_CKS, "← К списку"))


@router.callback_query(F.data.startswith(CB_TT_CK_UP), StateFilter("*"))
async def cb_tt_cookies_upload(cq: CallbackQuery, state: FSMContext, storage: Storage,
                              settings: Settings) -> None:
    acc_id = cq.data[len(CB_TT_CK_UP):]
    acc = storage.get_tiktok(acc_id)
    if acc is None:
        await cq.answer("Не найден", show_alert=True)
        return
    await state.set_state(UploadCookies.waiting_doc)
    await state.update_data(account_id=acc_id)
    await _edit(
        cq,
        f"📤 <b>Загрузка cookies для @{escape(acc.username)}</b>\n\n"
        "Пришлите файл <code>cookies.txt</code> в этот чат <b>как документ</b> "
        "(не сжимая в фото).\n\n"
        "Если ещё не получили файл — нажмите кнопку с гайдом ниже.\n\n"
        "Отмена — /cancel или ❌.",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="ℹ️ Где их взять", callback_data=CB_TT_CK_HELP)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]),
    )


@router.callback_query(F.data.startswith(CB_TT_CK_DEL), StateFilter("*"))
async def cb_tt_cookies_delete(cq: CallbackQuery, state: FSMContext, storage: Storage,
                              settings: Settings) -> None:
    await state.clear()
    acc_id = cq.data[len(CB_TT_CK_DEL):]
    acc = storage.get_tiktok(acc_id)
    if acc is None:
        await cq.answer("Не найден", show_alert=True)
        return
    removed = cookies.remove_cookies(settings.secrets_folder, acc_id)
    await cq.answer("Cookies удалены" if removed else "Не было что удалять")
    # Перерисовываем экран этого аккаунта
    cq.data = f"{CB_TT_CK}{acc_id}"
    await cb_tt_cookies_account(cq, state, storage, settings)


@router.message(UploadCookies.waiting_doc, F.document)
async def msg_cookies_doc(message: Message, state: FSMContext, storage: Storage,
                          settings: Settings, bot: Bot) -> None:
    data = await state.get_data()
    acc_id = data.get("account_id")
    if not acc_id or storage.get_tiktok(acc_id) is None:
        await message.answer("Сессия потерялась — начните заново через 🍪 Cookies.")
        await state.clear()
        return

    doc = message.document
    if doc.file_size and doc.file_size > 1_000_000:
        await message.answer("Файл слишком большой (≥1 MB). Это точно cookies.txt?")
        return

    # Скачиваем содержимое через bot.download
    try:
        buf = await bot.download(doc)
        content = buf.read() if buf else b""
    except Exception as e:
        log.exception("Не удалось скачать документ")
        await message.answer(f"❌ Не смог скачать файл: <code>{escape(str(e))}</code>")
        return

    ok, reason = cookies.validate(content)
    if not ok:
        await message.answer(
            f"❌ Файл не похож на TikTok-cookies: <i>{escape(reason)}</i>\n\n"
            "Пришлите корректный или /cancel.",
        )
        return

    cookies.save_cookies(settings.secrets_folder, acc_id, content)
    await state.clear()
    acc = storage.get_tiktok(acc_id)
    note = f"\n\n<i>Замечание: {escape(reason)}</i>" if reason != "OK" else ""
    await message.answer(
        f"✅ Cookies сохранены для <b>@{escape(acc.username if acc else acc_id)}</b>.{note}\n\n"
        "Следующий цикл мониторинга и скачивания будет использовать их.",
        reply_markup=back_to(CB_TT_CKS, "← К cookies"),
    )


@router.message(UploadCookies.waiting_doc)
async def msg_cookies_not_doc(message: Message) -> None:
    await message.answer(
        "Это не документ. Пришлите файл cookies.txt именно как файл "
        "(в Telegram: 📎 → Файл → выберите cookies.txt). /cancel чтобы отменить.",
    )
