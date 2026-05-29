"""Resumable upload одного видео на YouTube Data API v3."""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError, ResumableUploadError
from googleapiclient.http import MediaFileUpload

from config import YouTubeSettings
from services import youtube_auth
from services.quota import Quota, UPLOAD_COST

log = logging.getLogger("utub.youtube.upload")

# quotaExceeded (403) сюда НЕ входит — это не transient, ждать до полуночи PT.
_RETRY_STATUSES = {500, 502, 503, 504}
_MAX_RETRIES = 5
_CHUNK_SIZE = 1024 * 1024 * 4  # 4 MiB

YT_TITLE_MAX = 100
YT_DESC_MAX = 5000
YT_TAGS_MAX = 30


@dataclass(slots=True)
class UploadRequest:
    video_path: Path
    title: str
    description: str
    tags: list[str]


@dataclass(slots=True)
class UploadResult:
    youtube_video_id: str
    privacy_status: str


class UploadFailed(RuntimeError):
    pass


def _ensure_shorts(title: str, description: str) -> tuple[str, str]:
    """Shorts = 9:16 + ≤3 мин + #Shorts. Дописываем хэштег, если нет."""
    if "#shorts" not in title.lower():
        title = f"{title} #Shorts".strip()
    if "#shorts" not in description.lower():
        description = f"{description.rstrip()}\n\n#Shorts"
    return title, description


def upload(
    request: UploadRequest,
    yt_settings: YouTubeSettings,
    tokens_dir: Path,
    keyring_user: str,
    client_secrets: Path,
    quota: Quota,
) -> UploadResult:
    quota.check(UPLOAD_COST)

    creds = youtube_auth.get_credentials(tokens_dir, keyring_user, client_secrets)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    title, description = _ensure_shorts(request.title or "video", request.description or "")
    body = {
        "snippet": {
            "title": title[:YT_TITLE_MAX],
            "description": description[:YT_DESC_MAX],
            "tags": [t[:30] for t in request.tags[:YT_TAGS_MAX] if t],
            "categoryId": yt_settings.category_id,
            "defaultLanguage": yt_settings.default_language,
            "defaultAudioLanguage": yt_settings.default_language,
        },
        "status": {
            "privacyStatus": yt_settings.privacy_status,
            "selfDeclaredMadeForKids": yt_settings.made_for_kids,
        },
    }

    media = MediaFileUpload(
        str(request.video_path),
        chunksize=_CHUNK_SIZE,
        resumable=True,
        mimetype="video/*",
    )

    insert = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = _execute_with_retry(insert)
    quota.record(UPLOAD_COST)

    video_id = response.get("id")
    if not video_id:
        raise UploadFailed(f"YouTube не вернул video id: {response!r}")

    privacy = response.get("status", {}).get("privacyStatus", "unknown")
    log.info("Загружено на YouTube: id=%s privacy=%s", video_id, privacy)
    return UploadResult(youtube_video_id=video_id, privacy_status=privacy)


def _execute_with_retry(insert_request) -> dict:
    response = None
    attempt = 0
    while response is None:
        try:
            _, response = insert_request.next_chunk()
        except HttpError as e:
            if e.resp.status in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                attempt += 1
                backoff = (2 ** attempt) + random.uniform(0, 1)
                log.warning("HTTP %s — ретрай %d/%d через %.1fс",
                            e.resp.status, attempt, _MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            raise UploadFailed(_format_http_error(e)) from e
        except ResumableUploadError as e:
            raise UploadFailed(f"Resumable upload error: {e}") from e
    return response


def _format_http_error(e: HttpError) -> str:
    try:
        content = e.content.decode("utf-8", errors="replace") if e.content else ""
    except Exception:
        content = ""
    return f"YouTube API {e.resp.status}: {content[:500]}"
