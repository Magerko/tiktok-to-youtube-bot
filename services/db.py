"""SQLite-очередь видео и история попыток. WAL, stdlib sqlite3."""
from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

log = logging.getLogger("utub.db")

S_DISCOVERED = "DISCOVERED"
S_DOWNLOADING = "DOWNLOADING"
S_AWAITING_REVIEW = "AWAITING_REVIEW"
S_READY = "READY"
S_UPLOADING = "UPLOADING"
S_DONE = "DONE"
S_FAILED = "FAILED"
S_SKIPPED = "SKIPPED"

ALL_STATUSES = (
    S_DISCOVERED, S_DOWNLOADING, S_AWAITING_REVIEW, S_READY,
    S_UPLOADING, S_DONE, S_FAILED, S_SKIPPED,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id             TEXT    NOT NULL,
    tiktok_account_id   TEXT    NOT NULL,
    tiktok_video_id     TEXT    NOT NULL,
    tiktok_url          TEXT    NOT NULL,
    status              TEXT    NOT NULL,
    local_path          TEXT,
    title               TEXT,
    description         TEXT,
    duration_sec        REAL,
    youtube_video_id    TEXT,
    review_chat_id      INTEGER,
    review_message_id   INTEGER,
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    UNIQUE (pair_id, tiktok_video_id)
);

CREATE INDEX IF NOT EXISTS ix_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS ix_videos_pair   ON videos(pair_id);

CREATE TABLE IF NOT EXISTS upload_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id     INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    stage        TEXT    NOT NULL,
    success      INTEGER NOT NULL,
    error        TEXT,
    created_at   TEXT    NOT NULL
);
"""


@dataclass
class Video:
    id: int
    pair_id: str
    tiktok_account_id: str
    tiktok_video_id: str
    tiktok_url: str
    status: str
    local_path: str | None
    title: str | None
    description: str | None
    duration_sec: float | None
    youtube_video_id: str | None
    review_chat_id: int | None
    review_message_id: int | None
    attempts: int
    last_error: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Video":
        return cls(**{k: row[k] for k in row.keys()})


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
        log.info("SQLite готов: %s", self.path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def enqueue(
        self, *, pair_id: str, tiktok_account_id: str,
        tiktok_video_id: str, tiktok_url: str,
        title: str | None = None, description: str | None = None,
        duration_sec: float | None = None,
    ) -> Video | None:
        """Идемпотентная вставка — None, если такая запись уже есть."""
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "SELECT id FROM videos WHERE pair_id=? AND tiktok_video_id=?",
                (pair_id, tiktok_video_id),
            )
            if cur.fetchone():
                return None
            cur = self._conn.execute(
                """
                INSERT INTO videos
                    (pair_id, tiktok_account_id, tiktok_video_id, tiktok_url,
                     status, title, description, duration_sec,
                     attempts, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,0,?,?)
                """,
                (pair_id, tiktok_account_id, tiktok_video_id, tiktok_url,
                 S_DISCOVERED, title, description, duration_sec, now, now),
            )
            video_id = cur.lastrowid
        return self.get(video_id)  # type: ignore[arg-type]

    def exists(self, pair_id: str, tiktok_video_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM videos WHERE pair_id=? AND tiktok_video_id=? LIMIT 1",
                (pair_id, tiktok_video_id),
            )
            return cur.fetchone() is not None

    def get(self, video_id: int) -> Video | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM videos WHERE id=?", (video_id,))
            row = cur.fetchone()
        return Video.from_row(row) if row else None

    def list_by_status(self, status: str, limit: int = 50) -> list[Video]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM videos WHERE status=? ORDER BY id ASC LIMIT ?",
                (status, limit),
            )
            rows = cur.fetchall()
        return [Video.from_row(r) for r in rows]

    def list_recent(self, limit: int = 20) -> list[Video]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM videos ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        return [Video.from_row(r) for r in rows]

    def stats(self) -> dict[str, int]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM videos GROUP BY status"
            )
            rows = cur.fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    def update(self, video_id: int, **fields) -> None:
        """Точечный апдейт колонок. updated_at обновляется автоматически."""
        if not fields:
            return
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k}=?" for k in fields)
        params = list(fields.values()) + [video_id]
        with self._lock:
            self._conn.execute(f"UPDATE videos SET {cols} WHERE id=?", params)

    def claim_next(self, from_status: str, to_status: str) -> Video | None:
        """Атомарно: SELECT первого from_status → UPDATE в to_status."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._conn.execute(
                    "SELECT * FROM videos WHERE status=? ORDER BY id ASC LIMIT 1",
                    (from_status,),
                )
                row = cur.fetchone()
                if not row:
                    self._conn.execute("COMMIT")
                    return None
                now = _now()
                self._conn.execute(
                    "UPDATE videos SET status=?, updated_at=? WHERE id=?",
                    (to_status, now, row["id"]),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            return self.get(row["id"])

    def record_attempt(self, video_id: int, stage: str, success: bool,
                       error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO upload_attempts (video_id, stage, success, error, created_at)
                VALUES (?,?,?,?,?)
                """,
                (video_id, stage, 1 if success else 0, error, _now()),
            )

    def mark_failed(self, video_id: int, error: str, stage: str = "unknown") -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE videos
                SET status=?, last_error=?, attempts=attempts+1, updated_at=?
                WHERE id=?
                """,
                (S_FAILED, error[:2000], _now(), video_id),
            )
            self._conn.execute(
                """
                INSERT INTO upload_attempts (video_id, stage, success, error, created_at)
                VALUES (?,?,0,?,?)
                """,
                (video_id, stage, error[:2000], _now()),
            )

    def retry(self, video_id: int) -> bool:
        """Вернуть FAILED-видео в DISCOVERED — пересобрать с нуля."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE videos SET status=?, last_error=NULL, updated_at=? WHERE id=? AND status=?",
                (S_DISCOVERED, _now(), video_id, S_FAILED),
            )
            return cur.rowcount > 0

    def delete(self, video_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM videos WHERE id=?", (video_id,))
            return cur.rowcount > 0

    def videos_for_pair(self, pair_id: str, limit: int = 10) -> list[Video]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM videos WHERE pair_id=? ORDER BY id DESC LIMIT ?",
                (pair_id, limit),
            )
            rows = cur.fetchall()
        return [Video.from_row(r) for r in rows]
