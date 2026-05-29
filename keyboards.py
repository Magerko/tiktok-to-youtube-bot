"""Inline-клавиатуры и callback-токены (callback_data ≤ 64 B)."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# main menu
CB_MAIN = "m:main"
CB_TT = "m:tt"
CB_YT = "m:yt"
CB_PR = "m:pr"
CB_QUEUE = "m:q"
CB_HELP = "m:help"

# tiktok accounts
CB_TT_ADD = "tt:add"
CB_TT_LIST = "tt:list:0"
CB_TT_LIST_P = "tt:list:"
CB_TT_DEL = "tt:del:"
CB_TT_TOG = "tt:tog:"

# cookies
CB_TT_CKS = "tt:cks"
CB_TT_CK = "tt:ck:"
CB_TT_CK_UP = "tt:ckup:"
CB_TT_CK_DEL = "tt:ckdel:"
CB_TT_CK_HELP = "tt:ckhelp"

# youtube channels
CB_YT_ADD = "yt:add"
CB_YT_LIST = "yt:list:0"
CB_YT_LIST_P = "yt:list:"
CB_YT_DEL = "yt:del:"
CB_YT_REAUTH = "yt:reauth:"

# per-channel client_secrets
CB_YT_S_HELP = "yt:shelp"
CB_YT_S_USE_SHARED = "yt:sshared"
CB_YT_S_UPLOAD = "yt:sup"

# pairs
CB_PR_ADD = "pr:add"
CB_PR_LIST = "pr:list:0"
CB_PR_LIST_P = "pr:list:"
CB_PR_DEL = "pr:del:"
CB_PR_MODE = "pr:mode:"
CB_PR_TOG = "pr:tog:"
CB_PR_PICK_TT = "pr:pt:"
CB_PR_PICK_YT = "pr:py:"
CB_PR_PICK_MODE = "pr:pm:"

# queue
CB_Q_RECENT = "q:recent"
CB_Q_RETRY = "q:retry:"
CB_Q_DEL = "q:del:"

# review
CB_RV_APPROVE = "rv:ok:"
CB_RV_EDIT = "rv:ed:"
CB_RV_SKIP = "rv:no:"

# common
CB_CANCEL = "cancel"
CB_NOOP = "noop"

PAGE_SIZE = 6


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎵 TikTok аккаунты", callback_data=CB_TT)
    kb.button(text="📺 YouTube каналы", callback_data=CB_YT)
    kb.button(text="🔗 Пары", callback_data=CB_PR)
    kb.button(text="📊 Очередь", callback_data=CB_QUEUE)
    kb.button(text="ℹ️ Справка", callback_data=CB_HELP)
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def tiktok_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить @username", callback_data=CB_TT_ADD)
    kb.button(text="📋 Список", callback_data=CB_TT_LIST)
    kb.button(text="🍪 Cookies", callback_data=CB_TT_CKS)
    kb.button(text="🏠 Главное", callback_data=CB_MAIN)
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def pick_secrets_method_kb(has_shared: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_shared:
        rows.append([InlineKeyboardButton(text="🔁 Использовать общий",
                                          callback_data=CB_YT_S_USE_SHARED)])
    rows.append([InlineKeyboardButton(text="📤 Загрузить отдельный",
                                      callback_data=CB_YT_S_UPLOAD)])
    rows.append([InlineKeyboardButton(text="ℹ️ Гайд: как получить",
                                      callback_data=CB_YT_S_HELP)])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cookies_account_screen_kb(account_id: str, has_cookies: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_cookies:
        rows.append([
            InlineKeyboardButton(text="🔄 Заменить",
                                 callback_data=f"{CB_TT_CK_UP}{account_id}"),
            InlineKeyboardButton(text="🗑 Удалить",
                                 callback_data=f"{CB_TT_CK_DEL}{account_id}"),
        ])
    else:
        rows.append([InlineKeyboardButton(text="📤 Загрузить cookies.txt",
                                          callback_data=f"{CB_TT_CK_UP}{account_id}")])
    rows.append([InlineKeyboardButton(text="ℹ️ Где их взять", callback_data=CB_TT_CK_HELP)])
    rows.append([InlineKeyboardButton(text="← К списку cookies", callback_data=CB_TT_CKS)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def youtube_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Подключить канал", callback_data=CB_YT_ADD)
    kb.button(text="📋 Список", callback_data=CB_YT_LIST)
    kb.button(text="🏠 Главное", callback_data=CB_MAIN)
    kb.adjust(2, 1)
    return kb.as_markup()


def pairs_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Создать пару", callback_data=CB_PR_ADD)
    kb.button(text="📋 Список", callback_data=CB_PR_LIST)
    kb.button(text="🏠 Главное", callback_data=CB_MAIN)
    kb.adjust(2, 1)
    return kb.as_markup()


def back_to(target: str = CB_MAIN, label: str = "🏠 Главное") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=target)]]
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL)]]
    )


def paginated(
    items: list,
    page: int,
    page_prefix: str,
    back_cb: str,
    row_builder,
) -> InlineKeyboardMarkup:
    """row_builder(item) -> list[InlineKeyboardButton]."""
    total = len(items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    chunk = items[start:start + PAGE_SIZE]

    rows: list[list[InlineKeyboardButton]] = []
    for item in chunk:
        rows.append(row_builder(item))

    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{page_prefix}{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=CB_NOOP))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{page_prefix}{page + 1}"))
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="← Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pick_mode_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Review", callback_data=f"{CB_PR_PICK_MODE}review"),
            InlineKeyboardButton(text="⚡ Auto", callback_data=f"{CB_PR_PICK_MODE}auto"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL)],
    ])


def review_card_kb(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"{CB_RV_APPROVE}{video_id}"),
            InlineKeyboardButton(text="✏️ Изменить заголовок", callback_data=f"{CB_RV_EDIT}{video_id}"),
        ],
        [
            InlineKeyboardButton(text="❌ Пропустить", callback_data=f"{CB_RV_SKIP}{video_id}"),
        ],
    ])
