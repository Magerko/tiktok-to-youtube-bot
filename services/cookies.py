"""Per-account cookies для yt-dlp — secrets/cookies/<tiktok_account_id>.txt."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("utub.cookies")

_NETSCAPE_HEADERS = ("# Netscape HTTP Cookie File", "# HTTP Cookie File")


def cookies_dir(secrets_folder: Path) -> Path:
    return secrets_folder / "cookies"


def cookies_path(secrets_folder: Path, account_id: str) -> Path:
    return cookies_dir(secrets_folder) / f"{account_id}.txt"


def has_cookies(secrets_folder: Path, account_id: str) -> bool:
    p = cookies_path(secrets_folder, account_id)
    return p.exists() and p.stat().st_size > 0


def get_cookiefile(secrets_folder: Path, account_id: str) -> str | None:
    if has_cookies(secrets_folder, account_id):
        return str(cookies_path(secrets_folder, account_id))
    return None


def save_cookies(secrets_folder: Path, account_id: str, content: bytes) -> Path:
    cookies_dir(secrets_folder).mkdir(parents=True, exist_ok=True)
    p = cookies_path(secrets_folder, account_id)
    p.write_bytes(content)
    log.info("Cookies сохранены: %s (%d байт)", p, len(content))
    return p


def remove_cookies(secrets_folder: Path, account_id: str) -> bool:
    p = cookies_path(secrets_folder, account_id)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError as e:
        log.warning("Не удалось удалить %s: %s", p, e)
        return False


def validate(content: bytes) -> tuple[bool, str]:
    """Sanity-чек. Возвращает (ok, reason)."""
    if not content:
        return False, "пустой файл"
    if len(content) > 1_000_000:
        return False, f"подозрительно большой ({len(content)} B), обычно <100 KB"
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        return False, "не текст"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False, "пустой файл"
    has_header = any(ln.startswith(h) for ln in lines[:3] for h in _NETSCAPE_HEADERS)
    has_tiktok = any("tiktok.com" in ln for ln in lines)
    if not has_tiktok:
        return False, "нет ни одной строки с tiktok.com — это правда cookies от TikTok?"
    if not has_header:
        return True, "без Netscape-заголовка (yt-dlp обычно справится)"
    return True, "OK"
