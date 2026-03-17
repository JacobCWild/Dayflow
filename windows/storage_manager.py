"""
StorageManager - handles SQLite database and file storage for Dayflow on Windows.
Data is stored in %APPDATA%/Dayflow/ (e.g. C:/Users/<user>/AppData/Roaming/Dayflow/).
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def get_app_data_dir() -> Path:
    """Return the Windows AppData directory for Dayflow, creating it if needed."""
    app_data = os.environ.get("APPDATA", os.path.expanduser("~"))
    path = Path(app_data) / "Dayflow"
    path.mkdir(parents=True, exist_ok=True)
    return path


class StorageManager:
    """Manages the SQLite database and screenshot files on disk."""

    def __init__(self):
        self.app_dir = get_app_data_dir()
        self.db_path = self.app_dir / "dayflow.sqlite"
        self.recordings_dir = self.app_dir / "recordings"
        self.recordings_dir.mkdir(exist_ok=True)
        self._init_db()
        logger.info("StorageManager initialised at %s", self.app_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS screenshots (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path     TEXT    NOT NULL,
                    captured_at   TEXT    NOT NULL,
                    idle_seconds  REAL    DEFAULT 0,
                    batch_id      INTEGER,
                    created_at    TEXT    DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS batches (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time  TEXT NOT NULL,
                    end_time    TEXT NOT NULL,
                    status      TEXT DEFAULT 'pending',
                    created_at  TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS timeline_cards (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id    INTEGER NOT NULL,
                    title       TEXT,
                    summary     TEXT,
                    start_time  TEXT NOT NULL,
                    end_time    TEXT NOT NULL,
                    category    TEXT DEFAULT 'other',
                    created_at  TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (batch_id) REFERENCES batches(id)
                );

                CREATE TABLE IF NOT EXISTS observations (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id       INTEGER NOT NULL,
                    screenshot_id  INTEGER,
                    description    TEXT,
                    created_at     TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (batch_id) REFERENCES batches(id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )

    # ------------------------------------------------------------------
    # Screenshots
    # ------------------------------------------------------------------

    def next_screenshot_path(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return self.recordings_dir / f"screenshot_{ts}.jpg"

    def save_screenshot(
        self,
        file_path: Path,
        captured_at: datetime,
        idle_seconds: float = 0.0,
    ) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO screenshots (file_path, captured_at, idle_seconds) VALUES (?, ?, ?)",
                (str(file_path), captured_at.isoformat(), idle_seconds),
            )
            return cur.lastrowid

    def get_unprocessed_screenshots(self, limit: int = 200) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM screenshots WHERE batch_id IS NULL ORDER BY captured_at LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_screenshots_for_batch(self, batch_id: int) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM screenshots WHERE batch_id = ? ORDER BY captured_at",
                (batch_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------

    def create_batch(
        self,
        start_time: datetime,
        end_time: datetime,
        screenshot_ids: List[int],
    ) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO batches (start_time, end_time, status) VALUES (?, ?, 'pending')",
                (start_time.isoformat(), end_time.isoformat()),
            )
            batch_id = cur.lastrowid
            for sid in screenshot_ids:
                conn.execute(
                    "UPDATE screenshots SET batch_id = ? WHERE id = ?",
                    (batch_id, sid),
                )
            return batch_id

    def update_batch_status(self, batch_id: int, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE batches SET status = ? WHERE id = ?",
                (status, batch_id),
            )

    def get_pending_batches(self) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM batches WHERE status = 'pending' ORDER BY start_time"
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Timeline cards
    # ------------------------------------------------------------------

    def save_timeline_card(
        self,
        batch_id: int,
        title: str,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        category: str = "other",
    ):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO timeline_cards
                   (batch_id, title, summary, start_time, end_time, category)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    batch_id,
                    title,
                    summary,
                    start_time.isoformat(),
                    end_time.isoformat(),
                    category,
                ),
            )

    def get_timeline_cards(self, date: Optional[datetime] = None) -> List[dict]:
        """Return all timeline cards for the given date (4 AM boundary, like the macOS app)."""
        if date is None:
            date = datetime.now()

        # Use a 4 AM boundary so late-night work belongs to the previous "day".
        if date.hour < 4:
            day_start = (date - timedelta(days=1)).replace(
                hour=4, minute=0, second=0, microsecond=0
            )
        else:
            day_start = date.replace(hour=4, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM timeline_cards
                   WHERE start_time >= ? AND start_time < ?
                   ORDER BY start_time""",
                (day_start.isoformat(), day_end.isoformat()),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    def save_observations(self, batch_id: int, observations: List[str]):
        with self._get_conn() as conn:
            for obs in observations:
                conn.execute(
                    "INSERT INTO observations (batch_id, description) VALUES (?, ?)",
                    (batch_id, obs),
                )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    # ------------------------------------------------------------------
    # Storage cleanup
    # ------------------------------------------------------------------

    def cleanup_old_files(self, max_size_gb: float = 5.0):
        """Delete the oldest screenshots when total storage exceeds *max_size_gb*."""
        max_bytes = int(max_size_gb * 1024 ** 3)
        jpgs = list(self.recordings_dir.glob("*.jpg"))
        total_size = sum(f.stat().st_size for f in jpgs if f.exists())

        if total_size <= max_bytes:
            return

        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, file_path FROM screenshots ORDER BY captured_at ASC"
            ).fetchall()

        for row in rows:
            if total_size <= max_bytes:
                break
            try:
                fp = Path(row["file_path"])
                if fp.exists():
                    total_size -= fp.stat().st_size
                    fp.unlink()
                with self._get_conn() as conn:
                    conn.execute("DELETE FROM screenshots WHERE id = ?", (row["id"],))
            except Exception as exc:
                logger.warning("Could not delete screenshot %s: %s", row["file_path"], exc)
