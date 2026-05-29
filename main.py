"""Точка входа: aiogram-бот + TikTok-монитор + pipeline в одном event loop."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from config import settings
from handlers import (
    common_router, info_router, pairs_router, review_router,
    tiktok_router, youtube_router,
)
from handlers.review import send_review_card
from middlewares import AdminOnlyMiddleware
from services.db import Database, Video
from services.pipeline import Pipeline
from services.storage import Storage
from services.tiktok_monitor import TikTokMonitor

logging.basicConfig(
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
log = logging.getLogger("utub.main")


def _build_fsm_storage() -> BaseStorage:
    if settings.redis_url:
        log.info("FSM: Redis (%s)", settings.redis_url)
        return RedisStorage.from_url(settings.redis_url)
    log.warning("FSM: MemoryStorage (состояния потеряются при рестарте)")
    return MemoryStorage()


async def main() -> None:
    if not settings.admin_users:
        log.warning("ADMIN_USERS пуст — бот никого не пустит к управлению")

    (settings.secrets_folder / "tokens").mkdir(parents=True, exist_ok=True)
    settings.download_folder.mkdir(parents=True, exist_ok=True)
    settings.data_folder.mkdir(parents=True, exist_ok=True)

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    fsm_storage = _build_fsm_storage()
    dp = Dispatcher(storage=fsm_storage)

    storage = Storage(settings.data_folder)
    db = Database(settings.data_folder / "state.sqlite")

    monitor = TikTokMonitor(storage, db, settings.check_interval, settings.secrets_folder)

    async def on_review(video: Video) -> None:
        await send_review_card(bot, db, storage, settings, video.id)

    pipeline = Pipeline(
        storage=storage,
        db=db,
        yt_settings=settings.youtube,
        download_folder=settings.download_folder,
        tokens_dir=settings.secrets_folder / "tokens",
        secrets_folder=settings.secrets_folder,
        data_folder=settings.data_folder,
        on_review_needed=on_review,
    )

    admin_mw = AdminOnlyMiddleware(settings.admin_users)
    dp.message.outer_middleware(admin_mw)
    dp.callback_query.outer_middleware(admin_mw)

    # common первым: /cancel и навигация должны побеждать state-фильтры
    dp.include_routers(
        common_router, info_router, tiktok_router, youtube_router,
        pairs_router, review_router,
    )

    @dp.startup()
    async def _on_startup() -> None:
        monitor.start()
        pipeline.start()
        log.info("Бот готов. Админов: %d", len(settings.admin_users))

    @dp.shutdown()
    async def _on_shutdown() -> None:
        log.info("Завершение…")
        await monitor.stop()
        await pipeline.stop()
        db.close()
        await fsm_storage.close()
        await bot.session.close()

    await dp.start_polling(
        bot,
        storage=storage,
        db=db,
        settings=settings,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановлено пользователем")
