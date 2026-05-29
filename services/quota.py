"""Суточная квота YouTube Data API. Per-канал, reset в полночь PT (как у Google)."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("utub.quota")

UPLOAD_COST = 1600
THUMBNAIL_COST = 50
LIST_COST = 1
DEFAULT_DAILY_QUOTA = 10_000

_RESET_TZ = ZoneInfo("America/Los_Angeles")


class QuotaExceeded(RuntimeError):
    pass


def _today() -> str:
    return datetime.now(_RESET_TZ).date().isoformat()


class Quota:
    def __init__(self, path: Path, daily_quota: int = DEFAULT_DAILY_QUOTA) -> None:
        self.path = path
        self.daily_quota = daily_quota
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"date": _today(), "units_used": 0}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("Файл квоты повреждён — сбрасываю")
            return {"date": _today(), "units_used": 0}
        if data.get("date") != _today():
            return {"date": _today(), "units_used": 0}
        return data

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def used(self) -> int:
        return int(self._load().get("units_used", 0))

    def remaining(self) -> int:
        return max(0, self.daily_quota - self.used())

    def check(self, units: int) -> None:
        if self.used() + units > self.daily_quota:
            raise QuotaExceeded(
                f"YouTube API квота исчерпана: {self.used()}/{self.daily_quota}, "
                f"нужно ещё {units}. Сброс в полночь PT."
            )

    def record(self, units: int) -> int:
        data = self._load()
        data["units_used"] = int(data.get("units_used", 0)) + units
        self._save(data)
        return data["units_used"]


def quota_for_channel(data_folder: Path, channel_internal_id: str) -> Quota:
    return Quota(data_folder / f"quota_{channel_internal_id}.json")
