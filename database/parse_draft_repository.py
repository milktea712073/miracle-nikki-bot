"""Persistence and review workflow for rule-based parse drafts."""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from database.database import ensure_database_initialized, get_connection
from parser.models import ParseDraft, SuitCandidate


LOGGER = logging.getLogger(__name__)
DraftStatus = Literal["auto", "needs_review", "pending", "reviewed", "approved", "rejected", "failed"]


@dataclass(frozen=True, slots=True)
class ParseDraftSaveResult:
    raw_post_id: int
    parse_draft_id: int
    action: Literal["inserted", "updated", "failed"]


def utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat()


class ParseDraftRepository:
    """Repository for parser drafts and their human review state."""

    def __init__(self, database_path: Path | None = None) -> None:
        self._database_path = database_path
        ensure_database_initialized(database_path)

    def _connect(self) -> sqlite3.Connection:
        return get_connection(self._database_path)

    def get_parse_draft_by_raw_post_id(
        self, raw_post_id: int, parser_version: str
    ) -> dict[str, object] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM parse_drafts WHERE raw_post_id = ? AND parser_version = ?",
                (raw_post_id, parser_version),
            ).fetchone()
            if row is None:
                return None
            columns = [item[0] for item in connection.execute(
                "SELECT * FROM parse_drafts LIMIT 0"
            ).description]
            result = dict(zip(columns, row, strict=True))
            result["suits"] = [
                suit[0]
                for suit in connection.execute(
                    "SELECT suit_name_candidate FROM parse_draft_suits "
                    "WHERE parse_draft_id = ? ORDER BY position",
                    (row[0],),
                ).fetchall()
            ]
            return result
        finally:
            connection.close()

    def list_pending_parse_drafts(self, limit: int) -> list[dict[str, object]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM parse_drafts WHERE status = 'pending' "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            columns = [item[0] for item in connection.execute(
                "SELECT * FROM parse_drafts LIMIT 0"
            ).description]
            return [dict(zip(columns, row, strict=True)) for row in rows]
        finally:
            connection.close()

    def replace_parse_draft_suits(
        self, parse_draft_id: int, suits: list[SuitCandidate], connection: sqlite3.Connection
    ) -> None:
        connection.execute("DELETE FROM parse_draft_suits WHERE parse_draft_id = ?", (parse_draft_id,))
        connection.executemany(
            "INSERT INTO parse_draft_suits "
            "(parse_draft_id, suit_name_candidate, position, confidence, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (parse_draft_id, suit.name, position, suit.confidence, suit.notes)
                for position, suit in enumerate(suits)
            ],
        )

    def save_parse_draft(
        self, raw_post_id: int, parser_version: str, draft: ParseDraft
    ) -> ParseDraftSaveResult:
        """Upsert a draft and candidate suits in a single transaction."""
        now = utc_now_iso8601()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            existing = connection.execute(
                "SELECT id FROM parse_drafts WHERE raw_post_id = ? AND parser_version = ?",
                (raw_post_id, parser_version),
            ).fetchone()
            values = (
                draft.title,
                draft.content_type_candidate,
                draft.event_name_candidate,
                draft.official_series_candidate,
                draft.period_type_candidate,
                draft.start_at_candidate,
                draft.end_at_candidate,
                draft.player_category_candidate,
                draft.acquisition_method_candidate,
                draft.confidence,
                draft.parser_notes,
                now,
            )
            if existing is None:
                cursor = connection.execute(
                    "INSERT INTO parse_drafts (raw_post_id, parser_version, status, title, content_type_candidate, "
                    "event_name_candidate, official_series_candidate, period_type_candidate, "
                    "start_at_candidate, end_at_candidate, player_category_candidate, "
                    "acquisition_method_candidate, confidence, parser_notes, error_message, "
                    "created_at, updated_at) "
                    "VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                    (raw_post_id, parser_version, *values, now),
                )
                draft_id = int(cursor.lastrowid)
                action: Literal["inserted", "updated"] = "inserted"
            else:
                draft_id = int(existing[0])
                connection.execute(
                    "UPDATE parse_drafts SET status = 'pending', title = ?, content_type_candidate = ?, "
                    "event_name_candidate = ?, official_series_candidate = ?, "
                    "period_type_candidate = ?, start_at_candidate = ?, end_at_candidate = ?, "
                    "player_category_candidate = ?, acquisition_method_candidate = ?, "
                    "confidence = ?, parser_notes = ?, error_message = NULL, updated_at = ? "
                    "WHERE id = ?",
                    (*values, draft_id),
                )
                action = "updated"

            self.replace_parse_draft_suits(draft_id, draft.suits, connection)
            connection.execute(
                "UPDATE raw_posts SET parse_status = 'parsed', parse_error = NULL WHERE id = ?",
                (raw_post_id,),
            )
            connection.commit()
            return ParseDraftSaveResult(raw_post_id, draft_id, action)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_failed_draft(
        self, raw_post_id: int, parser_version: str, error_message: str
    ) -> ParseDraftSaveResult:
        """Record a parser failure without losing the source raw post."""
        now = utc_now_iso8601()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            existing = connection.execute(
                "SELECT id FROM parse_drafts WHERE raw_post_id = ? AND parser_version = ?",
                (raw_post_id, parser_version),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    "INSERT INTO parse_drafts (raw_post_id, parser_version, status, "
                    "error_message, created_at, updated_at) VALUES (?, ?, 'failed', ?, ?, ?)",
                    (raw_post_id, parser_version, error_message, now, now),
                )
                draft_id = int(cursor.lastrowid)
            else:
                draft_id = int(existing[0])
                connection.execute(
                    "UPDATE parse_drafts SET status = 'failed', error_message = ?, "
                    "updated_at = ? WHERE id = ?",
                    (error_message, now, draft_id),
                )
            connection.execute(
                "UPDATE raw_posts SET parse_status = 'failed', parse_error = ? WHERE id = ?",
                (error_message, raw_post_id),
            )
            connection.commit()
            return ParseDraftSaveResult(raw_post_id, draft_id, "failed")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update_review_status(
        self, parse_draft_id: int, status: DraftStatus, review_notes: str | None
    ) -> None:
        """Apply a human review status and optional notes to a draft."""
        if status not in {"pending", "reviewed", "approved", "rejected", "failed"}:
            raise ValueError(f"Unsupported draft status: {status}")
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE parse_drafts SET status = ?, review_notes = ?, updated_at = ? WHERE id = ?",
                (status, review_notes, utc_now_iso8601(), parse_draft_id),
            )
            connection.commit()
        finally:
            connection.close()

    def list_raw_posts_for_parsing(
        self, limit: int, raw_post_id: int | None = None, force: bool = False
    ) -> list[dict[str, object]]:
        """List raw posts eligible for parser execution, newest first."""
        where = ["source = 'facebook'"]
        values: list[object] = []
        if raw_post_id is not None:
            where.append("id = ?")
            values.append(raw_post_id)
        if not force:
            where.append("parse_status = 'pending'")
        values.append(limit)
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id, content, source_post_id FROM raw_posts WHERE "
                + " AND ".join(where)
                + " ORDER BY published_at DESC LIMIT ?",
                values,
            ).fetchall()
            return [
                {"id": row[0], "content": row[1], "source_post_id": row[2]}
                for row in rows
            ]
        finally:
            connection.close()
