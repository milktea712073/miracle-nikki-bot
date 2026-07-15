"""Repository operations for approved Miracle Nikki knowledge-base data."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from database.database import ensure_database_initialized, get_connection


def utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeRepository:
    """Encapsulate SQL used by the knowledge-base import service."""

    def __init__(self, database_path: Path | None = None) -> None:
        self._database_path = database_path
        ensure_database_initialized(database_path)

    def connect(self) -> sqlite3.Connection:
        return get_connection(self._database_path)

    def get_parse_draft(self, connection: sqlite3.Connection, draft_id: int) -> dict[str, object] | None:
        row = connection.execute("SELECT * FROM parse_drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            return None
        columns = [item[0] for item in connection.execute("SELECT * FROM parse_drafts LIMIT 0").description]
        draft = dict(zip(columns, row, strict=True))
        draft["suits"] = [
            suit[0]
            for suit in connection.execute(
                "SELECT suit_name_candidate FROM parse_draft_suits "
                "WHERE parse_draft_id = ? ORDER BY position",
                (draft_id,),
            ).fetchall()
        ]
        return draft

    def get_draft_review(self, connection: sqlite3.Connection, draft_id: int) -> dict[str, object] | None:
        row = connection.execute("SELECT * FROM draft_reviews WHERE parse_draft_id = ?", (draft_id,)).fetchone()
        if row is None:
            return None
        columns = [item[0] for item in connection.execute("SELECT * FROM draft_reviews LIMIT 0").description]
        review = dict(zip(columns, row, strict=True))
        review["suits"] = connection.execute("SELECT suit_name, display_order, is_live2d, cost_text, notes FROM draft_review_suits WHERE draft_review_id = ? ORDER BY display_order", (row[0],)).fetchall()
        return review

    def update_event(self, connection: sqlite3.Connection, event_id: int, official_series: str | None, event_type_id: int | None, description: str | None) -> None:
        connection.execute("UPDATE events SET official_series = ?, event_type_id = ?, description = ?, updated_at = ? WHERE id = ?", (official_series, event_type_id, description, utc_now_iso8601(), event_id))

    def find_event_by_source_raw_post_id(
        self, connection: sqlite3.Connection, source_raw_post_id: int | None
    ) -> int | None:
        """Find the event created from one raw post, never by display name."""
        if source_raw_post_id is None:
            return None
        row = connection.execute(
            "SELECT id FROM events WHERE source_raw_post_id = ? ORDER BY id LIMIT 1",
            (source_raw_post_id,),
        ).fetchone()
        return int(row[0]) if row else None

    def create_event(
        self,
        connection: sqlite3.Connection,
        name: str,
        official_series: str | None,
        event_type_id: int | None,
        description: str | None,
        source_raw_post_id: int | None = None,
    ) -> int:
        now = utc_now_iso8601()
        cursor = connection.execute(
            "INSERT INTO events (name, official_series, event_type_id, description, created_at, updated_at, source_raw_post_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                official_series,
                event_type_id,
                description,
                now,
                now,
                source_raw_post_id,
            ),
        )
        return int(cursor.lastrowid)

    def upsert_auto_event(
        self,
        connection: sqlite3.Connection,
        name: str,
        official_series: str | None,
        description: str | None,
        raw_post_id: int,
        content_type: str = "event",
    ) -> int:
        """Create or safely enrich an automatically parsed event.

        A verified record is never modified by parser output.  For an auto record,
        parser values only replace fields when a concrete value is available.
        """
        row = connection.execute(
            "SELECT id, data_status FROM events WHERE source_raw_post_id = ? "
            "ORDER BY id LIMIT 1",
            (raw_post_id,),
        ).fetchone()
        now = utc_now_iso8601()
        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO events (
                    name, official_series, description, content_type, created_at, updated_at,
                    data_status, source_raw_post_id, created_via, updated_via
                ) VALUES (?, ?, ?, ?, ?, ?, 'auto', ?, 'auto', 'parser')
                """,
                (name, official_series, description, content_type, now, now, raw_post_id),
            )
            return int(cursor.lastrowid)
        event_id, data_status = int(row[0]), str(row[1])
        if data_status != "verified":
            connection.execute(
                """
                UPDATE events
                SET official_series = COALESCE(?, official_series),
                    description = COALESCE(?, description),
                    content_type = ?,
                    updated_at = ?, updated_via = 'parser',
                    data_status = 'auto'
                WHERE id = ?
                """,
                (official_series, description, content_type, now, event_id),
            )
        return event_id

    def mark_event_needs_review(self, connection: sqlite3.Connection, event_id: int) -> None:
        """Flag an auto-created event with missing core activity information."""
        connection.execute(
            "UPDATE events SET data_status = 'needs_review', updated_via = 'parser' WHERE id = ? AND data_status != 'verified'",
            (event_id,),
        )

    def find_suit(self, connection: sqlite3.Connection, name: str) -> int | None:
        row = connection.execute("SELECT id FROM suits WHERE name = ?", (name,)).fetchone()
        return int(row[0]) if row else None

    def create_suit(self, connection: sqlite3.Connection, name: str) -> int:
        now = utc_now_iso8601()
        cursor = connection.execute(
            "INSERT INTO suits (name, created_at, updated_at) VALUES (?, ?, ?)",
            (name, now, now),
        )
        return int(cursor.lastrowid)

    def upsert_auto_suit(
        self, connection: sqlite3.Connection, name: str, raw_post_id: int
    ) -> int:
        """Create a parser-discovered suit, preserving verified suits unchanged."""
        row = connection.execute(
            "SELECT id, data_status FROM suits WHERE name = ?", (name,)
        ).fetchone()
        if row is not None:
            return int(row[0])
        now = utc_now_iso8601()
        cursor = connection.execute(
            """
            INSERT INTO suits (
                name, created_at, updated_at, data_status, source_raw_post_id,
                created_via, updated_via
            ) VALUES (?, ?, ?, 'auto', ?, 'auto', 'parser')
            """,
            (name, now, now, raw_post_id),
        )
        return int(cursor.lastrowid)

    def find_event_period(
        self,
        connection: sqlite3.Connection,
        event_id: int,
        period_type: str,
        start_at: str | None,
        end_at: str | None,
    ) -> int | None:
        row = connection.execute(
            "SELECT id FROM event_periods WHERE event_id = ? AND period_type = ? "
            "AND start_at IS ? AND end_at IS ?",
            (event_id, period_type, start_at, end_at),
        ).fetchone()
        return int(row[0]) if row else None

    def create_event_period(
        self,
        connection: sqlite3.Connection,
        event_id: int,
        period_type: str,
        start_at: str | None,
        end_at: str | None,
        notes: str | None,
    ) -> int:
        cursor = connection.execute(
            "INSERT INTO event_periods (event_id, period_type, start_at, end_at, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, period_type, start_at, end_at, notes, utc_now_iso8601()),
        )
        return int(cursor.lastrowid)

    def create_auto_event_period(
        self,
        connection: sqlite3.Connection,
        event_id: int,
        period_type: str,
        start_at: str | None,
        end_at: str | None,
        notes: str | None,
        raw_post_id: int,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO event_periods (
                event_id, period_type, start_at, end_at, notes, created_at,
                data_status, source_raw_post_id, updated_via
            ) VALUES (?, ?, ?, ?, ?, ?, 'auto', ?, 'parser')
            """,
            (event_id, period_type, start_at, end_at, notes, utc_now_iso8601(), raw_post_id),
        )
        return int(cursor.lastrowid)

    def find_event_suit(self, connection: sqlite3.Connection, event_id: int, suit_id: int) -> int | None:
        row = connection.execute(
            "SELECT id FROM event_suits WHERE event_id = ? AND suit_id = ?",
            (event_id, suit_id),
        ).fetchone()
        return int(row[0]) if row else None

    def create_event_suit(
        self,
        connection: sqlite3.Connection,
        event_id: int,
        suit_id: int,
        acquisition_method_id: int | None,
        display_order: int,
        notes: str | None,
    ) -> int:
        cursor = connection.execute(
            "INSERT INTO event_suits "
            "(event_id, suit_id, acquisition_method_id, display_order, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_id, suit_id, acquisition_method_id, display_order, notes),
        )
        return int(cursor.lastrowid)

    def create_auto_event_suit(
        self,
        connection: sqlite3.Connection,
        event_id: int,
        suit_id: int,
        display_order: int,
        raw_post_id: int,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO event_suits (
                event_id, suit_id, display_order, data_status, source_raw_post_id, updated_via
            ) VALUES (?, ?, ?, 'auto', ?, 'parser')
            """,
            (event_id, suit_id, display_order, raw_post_id),
        )
        return int(cursor.lastrowid)

    def mark_auto_import_verified(
        self, connection: sqlite3.Connection, event_id: int, suit_ids: list[int]
    ) -> None:
        """Mark records confirmed through the human review/import workflow."""
        connection.execute(
            "UPDATE events SET data_status = 'verified', updated_via = 'admin' WHERE id = ?",
            (event_id,),
        )
        if not suit_ids:
            return
        placeholders = ", ".join("?" for _ in suit_ids)
        connection.execute(
            f"UPDATE suits SET data_status = 'verified', updated_via = 'admin' WHERE id IN ({placeholders})",
            suit_ids,
        )
        connection.execute(
            f"UPDATE event_suits SET data_status = 'verified', updated_via = 'admin' "
            f"WHERE event_id = ? AND suit_id IN ({placeholders})",
            [event_id, *suit_ids],
        )

    def upsert_cost_record(self, connection: sqlite3.Connection, event_id: int, suit_id: int | None, scope: str, cost_text: str, notes: str | None) -> None:
        row = connection.execute("SELECT id FROM cost_records WHERE event_id = ? AND suit_id IS ? AND cost_scope = ?", (event_id, suit_id, scope)).fetchone()
        if row is None:
            connection.execute("INSERT INTO cost_records (event_id, suit_id, cost_scope, cost_text, notes) VALUES (?, ?, ?, ?, ?)", (event_id, suit_id, scope, cost_text, notes))
        else:
            connection.execute("UPDATE cost_records SET cost_text = ?, notes = ? WHERE id = ?", (cost_text, notes, row[0]))
