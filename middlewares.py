import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

log = logging.getLogger("utub.mw")


class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, admins: frozenset[int]) -> None:
        self.admins = admins

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id in self.admins:
            return await handler(event, data)
        log.info("Доступ запрещён: %s (%s)", user.id, user.username)
        if isinstance(event, CallbackQuery):
            await event.answer("⛔️ Доступ только для администраторов.", show_alert=True)
        elif isinstance(event, Message):
            await event.answer("⛔️ Доступ только для администраторов.")
        return None
