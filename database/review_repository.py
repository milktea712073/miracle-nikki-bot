"""Persistence for human review data and reference-data seeds."""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from database.database import DATABASE_PATH, ensure_database_initialized, get_connection


EVENT_TYPES = ["普通活動", "體力套", "扭蛋", "大閣", "婚紗", "滿天繁星", "奇妙博物館", "童話夢鄉", "凝砂套裝", "奇淵之嶼", "福袋", "登入送", "破曉之戰", "璀璨華光"]
ACQUISITION_METHODS = ["花鑽", "儲值", "免費", "體力", "聯盟", "設計圖", "金幣", "其他"]
REVIEW_STATUSES = {"auto", "needs_review", "pending", "reviewed", "approved", "rejected", "ignored"}
_REFERENCE_DATA_PATHS: set[Path] = set()
_REFERENCE_DATA_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self._database_path = database_path
        ensure_database_initialized(database_path)
        self._ensure_reference_data()

    def _ensure_reference_data(self) -> None:
        """Seed admin reference options once, outside normal connection paths."""
        path = (self._database_path or DATABASE_PATH).resolve()
        with _REFERENCE_DATA_LOCK:
            if path in _REFERENCE_DATA_PATHS:
                return
            connection = get_connection(self._database_path)
            try:
                self.seed_reference_data(connection)
            finally:
                connection.close()
            _REFERENCE_DATA_PATHS.add(path)

    def _connect(self) -> sqlite3.Connection:
        return get_connection(self._database_path)

    @staticmethod
    def seed_reference_data(connection: sqlite3.Connection) -> None:
        connection.executemany(
            "INSERT OR IGNORE INTO event_types (name, is_active) VALUES (?, 1)",
            [(name,) for name in EVENT_TYPES],
        )
        connection.executemany(
            "INSERT OR IGNORE INTO acquisition_methods (name, is_active) VALUES (?, 1)",
            [(name,) for name in ACQUISITION_METHODS],
        )
        connection.commit()

    def get_reference_options(self, table: str) -> list[tuple[int, str]]:
        if table not in {"event_types", "acquisition_methods"}:
            raise ValueError("Unsupported reference table.")
        connection = self._connect()
        try:
            return [(int(row[0]), str(row[1])) for row in connection.execute(f"SELECT id, name FROM {table} WHERE is_active = 1 ORDER BY id")]
        finally:
            connection.close()

    def get_or_create_review(self, draft_id: int) -> dict[str, object]:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            review = connection.execute("SELECT * FROM draft_reviews WHERE parse_draft_id = ?", (draft_id,)).fetchone()
            if review is None:
                draft = connection.execute("SELECT event_name_candidate, official_series_candidate FROM parse_drafts WHERE id = ?", (draft_id,)).fetchone()
                if draft is None:
                    raise ValueError(f"Parse draft {draft_id} does not exist.")
                now = now_iso()
                cursor = connection.execute(
                    "INSERT INTO draft_reviews (parse_draft_id, confirmed_event_name, official_series, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (draft_id, draft[0], draft[1], now, now),
                )
                review_id = int(cursor.lastrowid)
                candidates = connection.execute("SELECT suit_name_candidate FROM parse_draft_suits WHERE parse_draft_id = ? ORDER BY position", (draft_id,)).fetchall()
                connection.executemany(
                    "INSERT INTO draft_review_suits (draft_review_id, suit_name, display_order) VALUES (?, ?, ?)",
                    [(review_id, row[0], position) for position, row in enumerate(candidates)],
                )
                connection.commit()
            else:
                connection.commit()
            return self._get_review(connection, draft_id)
        finally:
            connection.close()

    def _get_review(self, connection: sqlite3.Connection, draft_id: int) -> dict[str, object]:
        row = connection.execute("SELECT * FROM draft_reviews WHERE parse_draft_id = ?", (draft_id,)).fetchone()
        if row is None:
            raise ValueError(f"Review for draft {draft_id} does not exist.")
        columns = [item[0] for item in connection.execute("SELECT * FROM draft_reviews LIMIT 0").description]
        result = dict(zip(columns, row, strict=True))
        result["suits"] = [dict(zip(["id", "suit_name", "display_order", "is_live2d", "cost_text", "notes"], suit, strict=True)) for suit in connection.execute("SELECT id, suit_name, display_order, is_live2d, cost_text, notes FROM draft_review_suits WHERE draft_review_id = ? ORDER BY display_order", (row[0],)).fetchall()]
        return result

    def save_review(self, draft_id: int, **values: object) -> None:
        allowed = {"confirmed_event_name", "event_type_id", "acquisition_method_id", "official_series", "event_cost_text", "live2d_cost_text", "review_notes"}
        updates = {key: value for key, value in values.items() if key in allowed}
        review = self.get_or_create_review(draft_id)
        if not updates:
            return
        assignments = ", ".join(f"{key} = ?" for key in updates)
        connection = self._connect()
        try:
            connection.execute(f"UPDATE draft_reviews SET {assignments}, reviewed_at = ?, updated_at = ? WHERE id = ?", (*updates.values(), now_iso(), now_iso(), review["id"]))
            connection.commit()
        finally:
            connection.close()

    def replace_review_suits(self, draft_id: int, suits: list[dict[str, object]]) -> None:
        review = self.get_or_create_review(draft_id)
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            connection.execute("DELETE FROM draft_review_suits WHERE draft_review_id = ?", (review["id"],))
            connection.executemany("INSERT INTO draft_review_suits (draft_review_id, suit_name, display_order, is_live2d, cost_text, notes) VALUES (?, ?, ?, ?, ?, ?)", [(review["id"], item["suit_name"], position, int(bool(item.get("is_live2d"))), item.get("cost_text"), item.get("notes")) for position, item in enumerate(suits)])
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_draft_status(self, draft_id: int, status: str) -> None:
        if status not in REVIEW_STATUSES:
            raise ValueError("Unsupported review status.")
        connection = self._connect()
        try:
            connection.execute("UPDATE parse_drafts SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), draft_id))
            connection.commit()
        finally:
            connection.close()

    def validate_review_ready(self, draft_id: int) -> dict[str, object]:
        review = self.get_or_create_review(draft_id)
        missing = [field for field in ("confirmed_event_name", "event_type_id", "acquisition_method_id") if not review[field]]
        if not review["suits"]:
            missing.append("suits")
        if missing:
            raise ValueError("Review is incomplete: " + ", ".join(missing))
        return review

    def list_pending_reviews(self, limit: int) -> list[dict[str, object]]:
        connection = self._connect()
        try:
            rows = connection.execute("SELECT id, title FROM parse_drafts WHERE status = 'needs_review' ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
            return [{"id": int(row[0]), "title": row[1]} for row in rows]
        finally:
            connection.close()
