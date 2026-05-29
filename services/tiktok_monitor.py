"""Поллер TikTok-аккаунтов через yt-dlp extract_flat."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import yt_dlp

from services import cookies
from services.db import Database
from services.storage import Storage, TikTokAccount

log = logging.getLogger("utub.monitor")

# Хватает с запасом для periodic polling. Больше — дольше запрос.
PLAYLIST_END = 20

# Между аккаунтами — чтобы не словить rate-limit.
PER_ACCOUNT_PAUSE_SEC = 5


@dataclass(slots=True)
class _Entry:
    video_id: str
    url: str
    title: str | None
    description: str | None
    duration_sec: float | None


def _flat_opts(cookiefile: str | None = None) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": PLAYLIST_END,
        "skip_download": True,
        "ignoreerrors": True,
    }
    if cookiefile:
        opts["cookiefile"] = cookiefile
    return opts


def _fetch_user_entries_sync(username: str, cookiefile: str | None = None) -> list[_Entry]:
    url = f"https://www.tiktok.com/@{username}"
    with yt_dlp.YoutubeDL(_flat_opts(cookiefile)) as ydl:
        try:
            info = ydl.extract_info(url, download=False, process=False)
        except yt_dlp.utils.DownloadError as e:
            raise RuntimeError(f"yt-dlp не смог открыть {url}: {e}") from e
    if not info:
        return []
    entries = info.get("entries") or []
    out: list[_Entry] = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id")
        if not vid:
            continue
        entry_url = e.get("url") or f"https://www.tiktok.com/@{username}/video/{vid}"
        out.append(_Entry(
            video_id=str(vid),
            url=str(entry_url),
            title=(e.get("title") or "").strip() or None,
            description=(e.get("description") or "").strip() or None,
            duration_sec=float(e["duration"]) if e.get("duration") is not None else None,
        ))
    return out


async def _fetch_user_entries(username: str, cookiefile: str | None = None) -> list[_Entry]:
    return await asyncio.to_thread(_fetch_user_entries_sync, username, cookiefile)


class TikTokMonitor:
    def __init__(self, storage: Storage, db: Database, check_interval: int,
                 secrets_folder) -> None:
        self.storage = storage
        self.db = db
        self.check_interval = check_interval
        self.secrets_folder = secrets_folder
        self._task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()
        self.last_tick_at: str | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="tiktok-monitor")

    async def stop(self) -> None:
        self._shutdown.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        log.info("TikTok-монитор запущен, интервал %d сек", self.check_interval)
        try:
            while not self._shutdown.is_set():
                try:
                    await self._tick()
                except Exception:
                    log.exception("Ошибка в тике мониторинга")
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=self.check_interval)
                except asyncio.TimeoutError:
                    pass
        finally:
            log.info("TikTok-монитор остановлен")

    async def _tick(self) -> None:
        accounts = list(self.storage.active_tiktok())
        if not accounts:
            return
        log.info("Проверяю %d TikTok-аккаунтов", len(accounts))
        for acc in accounts:
            if self._shutdown.is_set():
                return
            try:
                await self._check_account(acc)
            except Exception:
                log.exception("Ошибка проверки @%s", acc.username)
            await asyncio.sleep(PER_ACCOUNT_PAUSE_SEC)

    async def _check_account(self, acc: TikTokAccount) -> None:
        cookiefile = cookies.get_cookiefile(self.secrets_folder, acc.id)
        entries = await _fetch_user_entries(acc.username, cookiefile)
        if not entries:
            log.warning(
                "@%s: yt-dlp вернул пустой список (cookies: %s)",
                acc.username, "есть" if cookiefile else "нет",
            )
            return

        # Первый запуск: фиксируем свежий ID, историю не льём.
        if acc.last_video_id is None:
            self.storage.set_tiktok_last_video(acc.id, entries[0].video_id)
            log.info("@%s: bootstrap, last_video_id=%s",
                     acc.username, entries[0].video_id)
            return

        new_entries: list[_Entry] = []
        for e in entries:
            if e.video_id == acc.last_video_id:
                break
            new_entries.append(e)

        if not new_entries:
            return

        # От старого к новому — чтобы порядок аплоада совпал с порядком публикаций.
        new_entries.reverse()

        pairs = self.storage.pairs_for_tiktok(acc.id)
        if not pairs:
            log.info("@%s: %d новых видео, но активных пар нет — пропускаю",
                     acc.username, len(new_entries))
            self.storage.set_tiktok_last_video(acc.id, entries[0].video_id)
            return

        enqueued = 0
        for entry in new_entries:
            for pair in pairs:
                if self.db.exists(pair.id, entry.video_id):
                    continue
                self.db.enqueue(
                    pair_id=pair.id,
                    tiktok_account_id=acc.id,
                    tiktok_video_id=entry.video_id,
                    tiktok_url=entry.url,
                    title=entry.title,
                    description=entry.description,
                    duration_sec=entry.duration_sec,
                )
                enqueued += 1

        self.storage.set_tiktok_last_video(acc.id, entries[0].video_id)
        log.info("@%s: новых %d, поставлено в очередь %d записей (пар: %d)",
                 acc.username, len(new_entries), enqueued, len(pairs))
