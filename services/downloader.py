"""yt-dlp обёртка для скачивания одного TikTok-видео."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

log = logging.getLogger("utub.downloader")


class DownloadError(RuntimeError):
    pass


@dataclass(slots=True)
class DownloadedVideo:
    path: Path
    title: str
    description: str
    duration_sec: float | None
    tags: list[str]


def _build_opts(output_dir: Path, cookiefile: str | None = None) -> dict:
    opts: dict = {
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
        "writethumbnail": False,
        "writeinfojson": False,
    }
    if cookiefile:
        opts["cookiefile"] = cookiefile
    return opts


def _download_sync(url: str, output_dir: Path, cookiefile: str | None = None) -> DownloadedVideo:
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = _build_opts(output_dir, cookiefile)
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            raise DownloadError(str(e)) from e

    if info is None:
        raise DownloadError(f"yt-dlp ничего не вернул для {url}")
    if "entries" in info and info.get("entries"):
        info = info["entries"][0]

    filename = (
        info.get("requested_downloads", [{}])[0].get("filepath")
        if info.get("requested_downloads") else None
    )
    if not filename:
        filename = info.get("_filename") or info.get("filename")
    if not filename or not Path(filename).exists():
        candidate = output_dir / f"{info.get('id')}.{info.get('ext', 'mp4')}"
        if candidate.exists():
            filename = str(candidate)
    if not filename or not Path(filename).exists():
        raise DownloadError(f"Не удалось определить путь скачанного файла для {url}")

    title = (info.get("title") or info.get("fulltitle") or "").strip()
    description = (info.get("description") or info.get("alt_title") or "").strip()
    duration = info.get("duration")
    tags = info.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    log.info("Скачано: %s (%s сек) → %s", title or info.get("id"), duration, filename)
    return DownloadedVideo(
        path=Path(filename),
        title=title or "",
        description=description or "",
        duration_sec=float(duration) if duration is not None else None,
        tags=[str(t) for t in tags],
    )


async def download(url: str, output_dir: Path,
                   cookiefile: str | None = None) -> DownloadedVideo:
    return await asyncio.to_thread(_download_sync, url, output_dir, cookiefile)
