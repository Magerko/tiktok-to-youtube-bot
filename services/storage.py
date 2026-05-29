"""JSON-хранилище: TikTok-аккаунты, YouTube-каналы, пары.

ID — 8-hex, чтобы укладываться в Telegram callback_data (64 B).
"""
from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal

log = logging.getLogger("utub.storage")

Mode = Literal["review", "auto"]


@dataclass
class TikTokAccount:
    id: str
    username: str
    display_name: str
    added_at: str
    enabled: bool
    last_video_id: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "added_at": self.added_at,
            "enabled": self.enabled,
            "last_video_id": self.last_video_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TikTokAccount":
        return cls(
            id=d["id"],
            username=d["username"],
            display_name=d.get("display_name") or d["username"],
            added_at=d.get("added_at", ""),
            enabled=d.get("enabled", True),
            last_video_id=d.get("last_video_id"),
        )


@dataclass
class YouTubeChannel:
    id: str
    title: str
    youtube_channel_id: str | None  # UC..., приходит после OAuth
    keyring_user: str
    added_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "youtube_channel_id": self.youtube_channel_id,
            "keyring_user": self.keyring_user,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "YouTubeChannel":
        return cls(
            id=d["id"],
            title=d.get("title", d["id"]),
            youtube_channel_id=d.get("youtube_channel_id"),
            keyring_user=d["keyring_user"],
            added_at=d.get("added_at", ""),
        )


@dataclass
class Pair:
    id: str
    tiktok_account_id: str
    youtube_channel_id: str
    mode: Mode
    enabled: bool
    added_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tiktok_account_id": self.tiktok_account_id,
            "youtube_channel_id": self.youtube_channel_id,
            "mode": self.mode,
            "enabled": self.enabled,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Pair":
        mode = d.get("mode", "review")
        if mode not in ("review", "auto"):
            mode = "review"
        return cls(
            id=d["id"],
            tiktok_account_id=d["tiktok_account_id"],
            youtube_channel_id=d["youtube_channel_id"],
            mode=mode,  # type: ignore[arg-type]
            enabled=d.get("enabled", True),
            added_at=d.get("added_at", ""),
        )


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return secrets.token_hex(4)


class Storage:
    def __init__(self, data_folder: str | Path) -> None:
        self.data_folder = Path(data_folder)
        self.tiktok_file = self.data_folder / "tiktok_accounts.json"
        self.youtube_file = self.data_folder / "youtube_channels.json"
        self.pairs_file = self.data_folder / "pairs.json"
        self.tiktok: dict[str, TikTokAccount] = {}
        self.youtube: dict[str, YouTubeChannel] = {}
        self.pairs: dict[str, Pair] = {}
        self._ensure_files()
        self._load()

    # ── persistence ─────────────────────────────────────────────────────────
    def _ensure_files(self) -> None:
        self.data_folder.mkdir(parents=True, exist_ok=True)
        for f, default in (
            (self.tiktok_file, {"accounts": []}),
            (self.youtube_file, {"channels": []}),
            (self.pairs_file, {"pairs": []}),
        ):
            if not f.exists():
                self._write(f, default)

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        tmp.replace(path)

    def _load(self) -> None:
        self.tiktok = self._load_one(self.tiktok_file, "accounts", TikTokAccount)
        self.youtube = self._load_one(self.youtube_file, "channels", YouTubeChannel)
        self.pairs = self._load_one(self.pairs_file, "pairs", Pair)
        log.info(
            "Загружено: TikTok=%d, YouTube=%d, пар=%d",
            len(self.tiktok), len(self.youtube), len(self.pairs),
        )

    @staticmethod
    def _load_one(path: Path, key: str, cls) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f).get(key, [])
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("Файл %s повреждён, начинаю с пустого: %s", path, e)
            return {}
        out: dict = {}
        for item in raw:
            try:
                obj = cls.from_dict(item)
                out[obj.id] = obj
            except Exception:
                log.exception("Битая запись в %s: %r — пропускаю", path, item)
        return out

    def _save_tiktok(self) -> None:
        self._write(self.tiktok_file, {"accounts": [a.to_dict() for a in self.tiktok.values()]})

    def _save_youtube(self) -> None:
        self._write(self.youtube_file, {"channels": [c.to_dict() for c in self.youtube.values()]})

    def _save_pairs(self) -> None:
        self._write(self.pairs_file, {"pairs": [p.to_dict() for p in self.pairs.values()]})

    # ── TikTok accounts ─────────────────────────────────────────────────────
    def add_tiktok(self, username: str,
                   display_name: str | None = None) -> TikTokAccount | None:
        username = username.lstrip("@").strip()
        if not username:
            return None
        if any(a.username.lower() == username.lower() for a in self.tiktok.values()):
            return None
        acc = TikTokAccount(
            id=_new_id(),
            username=username,
            display_name=display_name or username,
            added_at=_now(),
            enabled=True,
            last_video_id=None,
        )
        self.tiktok[acc.id] = acc
        self._save_tiktok()
        return acc

    def remove_tiktok(self, account_id: str) -> bool:
        if account_id not in self.tiktok:
            return False
        for pair_id in [p.id for p in self.pairs.values()
                        if p.tiktok_account_id == account_id]:
            self.pairs.pop(pair_id, None)
        self._save_pairs()
        self.tiktok.pop(account_id)
        self._save_tiktok()
        return True

    def get_tiktok(self, account_id: str) -> TikTokAccount | None:
        return self.tiktok.get(account_id)

    def list_tiktok(self) -> list[TikTokAccount]:
        return sorted(self.tiktok.values(), key=lambda a: a.username.lower())

    def set_tiktok_last_video(self, account_id: str, video_id: str) -> None:
        acc = self.tiktok.get(account_id)
        if acc is None:
            return
        acc.last_video_id = video_id
        self._save_tiktok()

    def set_tiktok_enabled(self, account_id: str, enabled: bool) -> bool:
        acc = self.tiktok.get(account_id)
        if acc is None:
            return False
        acc.enabled = enabled
        self._save_tiktok()
        return True

    # ── YouTube channels ────────────────────────────────────────────────────
    def add_youtube(self, title: str) -> YouTubeChannel:
        ch_id = _new_id()
        ch = YouTubeChannel(
            id=ch_id,
            title=title.strip() or ch_id,
            youtube_channel_id=None,
            keyring_user=f"yt-token-{ch_id}",
            added_at=_now(),
        )
        self.youtube[ch.id] = ch
        self._save_youtube()
        return ch

    def remove_youtube(self, channel_id: str) -> bool:
        if channel_id not in self.youtube:
            return False
        for pair_id in [p.id for p in self.pairs.values() if p.youtube_channel_id == channel_id]:
            self.pairs.pop(pair_id, None)
        self._save_pairs()
        self.youtube.pop(channel_id)
        self._save_youtube()
        return True

    def get_youtube(self, channel_id: str) -> YouTubeChannel | None:
        return self.youtube.get(channel_id)

    def list_youtube(self) -> list[YouTubeChannel]:
        return sorted(self.youtube.values(), key=lambda c: c.title.lower())

    def update_youtube_meta(self, channel_id: str, title: str | None = None,
                            youtube_channel_id: str | None = None) -> bool:
        ch = self.youtube.get(channel_id)
        if ch is None:
            return False
        if title is not None:
            ch.title = title
        if youtube_channel_id is not None:
            ch.youtube_channel_id = youtube_channel_id
        self._save_youtube()
        return True

    # ── Pairs ───────────────────────────────────────────────────────────────
    def add_pair(self, tiktok_account_id: str, youtube_channel_id: str,
                 mode: Mode = "review") -> Pair | None:
        if tiktok_account_id not in self.tiktok or youtube_channel_id not in self.youtube:
            return None
        for p in self.pairs.values():
            if (p.tiktok_account_id == tiktok_account_id
                    and p.youtube_channel_id == youtube_channel_id):
                return None
        pair = Pair(
            id=_new_id(),
            tiktok_account_id=tiktok_account_id,
            youtube_channel_id=youtube_channel_id,
            mode=mode,
            enabled=True,
            added_at=_now(),
        )
        self.pairs[pair.id] = pair
        self._save_pairs()
        return pair

    def remove_pair(self, pair_id: str) -> bool:
        if pair_id not in self.pairs:
            return False
        self.pairs.pop(pair_id)
        self._save_pairs()
        return True

    def get_pair(self, pair_id: str) -> Pair | None:
        return self.pairs.get(pair_id)

    def list_pairs(self) -> list[Pair]:
        return list(self.pairs.values())

    def pairs_for_tiktok(self, tiktok_account_id: str) -> list[Pair]:
        return [p for p in self.pairs.values()
                if p.tiktok_account_id == tiktok_account_id and p.enabled]

    def set_pair_mode(self, pair_id: str, mode: Mode) -> bool:
        p = self.pairs.get(pair_id)
        if p is None:
            return False
        p.mode = mode
        self._save_pairs()
        return True

    def set_pair_enabled(self, pair_id: str, enabled: bool) -> bool:
        p = self.pairs.get(pair_id)
        if p is None:
            return False
        p.enabled = enabled
        self._save_pairs()
        return True

    # ── utility ─────────────────────────────────────────────────────────────
    def active_tiktok(self) -> Iterable[TikTokAccount]:
        return (a for a in self.tiktok.values() if a.enabled)
