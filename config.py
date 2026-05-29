import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _parse_admins(raw: str) -> frozenset[int]:
    return frozenset(int(x.strip()) for x in raw.split(",") if x.strip())


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Переменная окружения {name} обязательна. Заполните .env")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class YouTubeSettings:
    # Опциональный общий fallback. Per-channel файлы перебивают.
    client_secrets: Path | None
    privacy_status: str
    category_id: str
    default_language: str
    made_for_kids: bool


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_users: frozenset[int]
    check_interval: int
    data_folder: Path
    download_folder: Path
    secrets_folder: Path
    redis_url: str | None
    youtube: YouTubeSettings

    @property
    def primary_admin(self) -> int | None:
        return next(iter(sorted(self.admin_users)), None)


def _build() -> Settings:
    data_folder = Path(os.getenv("DATA_FOLDER", "pydata"))
    download_folder = Path(os.getenv("DOWNLOAD_FOLDER", "downloads"))
    secrets_folder = Path(os.getenv("SECRETS_FOLDER", "secrets"))
    raw_secrets = os.getenv("YOUTUBE_CLIENT_SECRETS")
    client_secrets: Path | None = Path(raw_secrets) if raw_secrets else None

    return Settings(
        bot_token=_required("TELEGRAM_BOT_TOKEN"),
        admin_users=_parse_admins(os.getenv("ADMIN_USERS", "")),
        check_interval=int(os.getenv("CHECK_INTERVAL", "600")),
        data_folder=data_folder,
        download_folder=download_folder,
        secrets_folder=secrets_folder,
        redis_url=os.getenv("REDIS_URL") or None,
        youtube=YouTubeSettings(
            client_secrets=client_secrets,
            privacy_status=os.getenv("YT_PRIVACY", "public"),
            category_id=os.getenv("YT_CATEGORY_ID", "22"),
            default_language=os.getenv("YT_DEFAULT_LANGUAGE", "ru"),
            made_for_kids=_bool("YT_MADE_FOR_KIDS", False),
        ),
    )


settings = _build()
