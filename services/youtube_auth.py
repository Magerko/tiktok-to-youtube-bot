"""OAuth installed-app для YouTube Data API.

Per-channel: токены в secrets/tokens/<keyring_user>.json,
client_secrets — secrets/client_secrets/<youtube_channel.id>.json
(fallback на общий путь из YouTubeSettings.client_secrets).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

log = logging.getLogger("utub.youtube.auth")

# readonly нужен, чтобы при первой авторизации забрать UC-id через channels.list mine=true.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


class AuthError(RuntimeError):
    pass


def _token_path(tokens_dir: Path, keyring_user: str) -> Path:
    return tokens_dir / f"{keyring_user}.json"


def load_credentials(tokens_dir: Path, keyring_user: str) -> Credentials | None:
    path = _token_path(tokens_dir, keyring_user)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Credentials.from_authorized_user_info(data, SCOPES)
    except Exception:
        log.exception("Битый токен %s — удаляю", path)
        try:
            path.unlink()
        except OSError:
            pass
        return None


def save_credentials(tokens_dir: Path, keyring_user: str, creds: Credentials) -> None:
    tokens_dir.mkdir(parents=True, exist_ok=True)
    path = _token_path(tokens_dir, keyring_user)
    path.write_text(creds.to_json(), encoding="utf-8")


def clear_credentials(tokens_dir: Path, keyring_user: str) -> None:
    path = _token_path(tokens_dir, keyring_user)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            log.warning("Не удалось удалить токен %s", path)


def has_credentials(tokens_dir: Path, keyring_user: str) -> bool:
    return load_credentials(tokens_dir, keyring_user) is not None


def get_credentials(tokens_dir: Path, keyring_user: str,
                    client_secrets: Path | None = None) -> Credentials:
    """Рабочие учётки: load → refresh → OAuth flow в браузере."""
    creds = load_credentials(tokens_dir, keyring_user)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(tokens_dir, keyring_user, creds)
        return creds

    if client_secrets is None or not client_secrets.exists():
        raise AuthError(
            f"Нет токена для канала '{keyring_user}' и не найден client_secrets.json — "
            "сначала пройдите OAuth (➕ Добавить YouTube-канал в боте)."
        )

    log.info("Запускаю OAuth installed-app flow для %s", keyring_user)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message="Открой ссылку в браузере для авторизации YouTube…",
        success_message="Готово, можно закрывать вкладку.",
    )
    save_credentials(tokens_dir, keyring_user, creds)
    return creds


def client_secrets_dir(secrets_folder: Path) -> Path:
    return secrets_folder / "client_secrets"


def client_secrets_path(secrets_folder: Path, channel_internal_id: str) -> Path:
    return client_secrets_dir(secrets_folder) / f"{channel_internal_id}.json"


def has_client_secrets(secrets_folder: Path, channel_internal_id: str) -> bool:
    return client_secrets_path(secrets_folder, channel_internal_id).exists()


def save_client_secrets(secrets_folder: Path, channel_internal_id: str,
                        content: bytes) -> Path:
    d = client_secrets_dir(secrets_folder)
    d.mkdir(parents=True, exist_ok=True)
    p = client_secrets_path(secrets_folder, channel_internal_id)
    p.write_bytes(content)
    log.info("client_secrets сохранён: %s", p)
    return p


def remove_client_secrets(secrets_folder: Path, channel_internal_id: str) -> bool:
    p = client_secrets_path(secrets_folder, channel_internal_id)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError as e:
        log.warning("Не удалось удалить %s: %s", p, e)
        return False


def validate_client_secrets(content: bytes) -> tuple[bool, str]:
    """Должен быть JSON OAuth Desktop client'а Google."""
    if not content:
        return False, "пустой файл"
    if len(content) > 100_000:
        return False, f"подозрительно большой ({len(content)} B), обычно <5 KB"
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return False, f"не JSON: {e}"
    if not isinstance(data, dict):
        return False, "корень JSON не объект"
    installed = data.get("installed") or data.get("web")
    if not installed:
        return False, "нет ключа 'installed' (Desktop) или 'web'"
    if not installed.get("client_id"):
        return False, "нет installed.client_id"
    if not installed.get("client_secret"):
        return False, "нет installed.client_secret"
    if data.get("web") and not data.get("installed"):
        return True, "это Web-client; обычно нужен Desktop. Может не работать"
    return True, "OK"


def resolve_client_secrets(secrets_folder: Path, channel_internal_id: str,
                           legacy_fallback: Path | None) -> Path:
    """Per-channel → legacy fallback → AuthError."""
    per = client_secrets_path(secrets_folder, channel_internal_id)
    if per.exists():
        return per
    if legacy_fallback is not None and legacy_fallback.exists():
        return legacy_fallback
    raise AuthError(
        f"Нет client_secrets для канала {channel_internal_id}. "
        "Подключите свой через бота: 📺 YouTube → 🔄 Re-auth."
    )


def fetch_my_channel(creds: Credentials) -> tuple[str, str] | None:
    """(channel_id, title) или None если у юзера нет YouTube-канала. 1 unit."""
    from googleapiclient.discovery import build

    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    resp = yt.channels().list(part="snippet", mine=True, maxResults=1).execute()
    items = resp.get("items") or []
    if not items:
        return None
    return items[0]["id"], items[0]["snippet"]["title"]
