"""Оркестратор очереди видео.

    DISCOVERED → DOWNLOADING → AWAITING_REVIEW|READY → UPLOADING → DONE
                                                                 └► FAILED
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from config import YouTubeSettings
from services import cookies, downloader, youtube_auth, youtube_upload
from services.db import (
    Database, Video,
    S_AWAITING_REVIEW, S_DISCOVERED, S_DONE, S_DOWNLOADING,
    S_FAILED, S_READY, S_UPLOADING,
)
from services.quota import QuotaExceeded, quota_for_channel
from services.storage import Storage

log = logging.getLogger("utub.pipeline")

TICK_SEC = 5

ReviewCallback = Callable[[Video], Awaitable[None]]


class Pipeline:
    def __init__(
        self,
        storage: Storage,
        db: Database,
        yt_settings: YouTubeSettings,
        download_folder: Path,
        tokens_dir: Path,
        secrets_folder: Path,
        data_folder: Path,
        on_review_needed: ReviewCallback,
    ) -> None:
        self.storage = storage
        self.db = db
        self.yt_settings = yt_settings
        self.download_folder = download_folder
        self.tokens_dir = tokens_dir
        self.secrets_folder = secrets_folder
        self.data_folder = data_folder
        self.on_review_needed = on_review_needed

        self._task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="pipeline")

    async def stop(self) -> None:
        self._shutdown.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        log.info("Pipeline запущен (tick %dс)", TICK_SEC)
        try:
            while not self._shutdown.is_set():
                did_work = False
                try:
                    did_work = await self._process_one_download() or did_work
                    did_work = await self._process_one_upload() or did_work
                except Exception:
                    log.exception("Сбой в pipeline-тике")
                if not did_work:
                    try:
                        await asyncio.wait_for(self._shutdown.wait(), timeout=TICK_SEC)
                    except asyncio.TimeoutError:
                        pass
        finally:
            log.info("Pipeline остановлен")

    # ── stage 1: download ───────────────────────────────────────────────────
    async def _process_one_download(self) -> bool:
        video = self.db.claim_next(S_DISCOVERED, S_DOWNLOADING)
        if video is None:
            return False
        log.info("⬇️ Скачиваю %s (video #%d) → pair %s",
                 video.tiktok_video_id, video.id, video.pair_id)
        cookiefile = cookies.get_cookiefile(self.secrets_folder, video.tiktok_account_id)
        try:
            result = await downloader.download(
                video.tiktok_url, self.download_folder, cookiefile=cookiefile,
            )
        except downloader.DownloadError as e:
            log.warning("Download failed: %s", e)
            self.db.mark_failed(video.id, str(e), stage="download")
            return True
        except Exception as e:
            log.exception("Неожиданная ошибка скачивания")
            self.db.mark_failed(video.id, repr(e), stage="download")
            return True

        # flat-extract обычно не отдаёт caption — берём то, что нашлось при полном download.
        new_title = result.title or video.title or ""
        new_desc = result.description or video.description or ""

        pair = self.storage.get_pair(video.pair_id)
        if pair is None:
            log.error("Пара %s исчезла — отмечаю видео FAILED", video.pair_id)
            self.db.mark_failed(video.id, "Pair deleted", stage="resolve_pair")
            return True

        next_status = S_AWAITING_REVIEW if pair.mode == "review" else S_READY
        self.db.update(
            video.id,
            status=next_status,
            local_path=str(result.path),
            title=new_title,
            description=new_desc,
            duration_sec=result.duration_sec,
        )
        self.db.record_attempt(video.id, stage="download", success=True)

        if next_status == S_AWAITING_REVIEW:
            try:
                fresh = self.db.get(video.id)
                if fresh is not None:
                    await self.on_review_needed(fresh)
            except Exception:
                log.exception("Не удалось отправить review-карточку для video #%d", video.id)
        else:
            log.info("✅ Скачано, режим auto → READY: video #%d", video.id)
        return True

    # ── stage 2: upload ─────────────────────────────────────────────────────
    async def _process_one_upload(self) -> bool:
        video = self.db.claim_next(S_READY, S_UPLOADING)
        if video is None:
            return False

        pair = self.storage.get_pair(video.pair_id)
        if pair is None:
            self.db.mark_failed(video.id, "Pair deleted", stage="resolve_pair")
            return True
        channel = self.storage.get_youtube(pair.youtube_channel_id)
        if channel is None:
            self.db.mark_failed(video.id, "YouTube channel deleted", stage="resolve_channel")
            return True
        if not video.local_path or not Path(video.local_path).exists():
            self.db.mark_failed(video.id, f"Файл не найден: {video.local_path}",
                                stage="resolve_file")
            return True

        log.info("⬆️ Заливаю video #%d → канал '%s' (%s)",
                 video.id, channel.title, channel.youtube_channel_id or "?")

        try:
            client_secrets = youtube_auth.resolve_client_secrets(
                self.secrets_folder, channel.id, self.yt_settings.client_secrets,
            )
        except youtube_auth.AuthError as e:
            self.db.mark_failed(video.id, str(e), stage="resolve_secrets")
            return True

        quota = quota_for_channel(self.data_folder, channel.id)

        request = youtube_upload.UploadRequest(
            video_path=Path(video.local_path),
            title=video.title or "video",
            description=video.description or "",
            tags=[],
        )
        try:
            result = await asyncio.to_thread(
                youtube_upload.upload,
                request, self.yt_settings, self.tokens_dir,
                channel.keyring_user, client_secrets, quota,
            )
        except QuotaExceeded as e:
            log.warning("Квота '%s' исчерпана: %s", channel.title, e)
            self.db.update(video.id, status=S_READY, last_error=str(e))
            self.db.record_attempt(video.id, stage="upload", success=False, error=str(e))
            await asyncio.sleep(60)
            return True
        except youtube_upload.UploadFailed as e:
            log.warning("Upload failed: %s", e)
            self.db.mark_failed(video.id, str(e), stage="upload")
            return True
        except Exception as e:
            log.exception("Неожиданная ошибка аплоада")
            self.db.mark_failed(video.id, repr(e), stage="upload")
            return True

        self.db.update(
            video.id,
            status=S_DONE,
            youtube_video_id=result.youtube_video_id,
        )
        self.db.record_attempt(video.id, stage="upload", success=True)

        # Локальный файл больше не нужен — на retry скачаем заново.
        try:
            Path(video.local_path).unlink(missing_ok=True)
        except OSError as e:
            log.warning("Не удалось удалить %s: %s", video.local_path, e)

        log.info("🎉 Готово: https://youtu.be/%s", result.youtube_video_id)
        return True
