"""Persistence and review workflow for rule-based parse drafts."""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Sequence

from content.section_splitter import NoticeSection, split_notice_sections
from database.database import ensure_database_initialized, get_connection
from parser.models import ParseDraft, SuitCandidate


LOGGER = logging.getLogger(__name__)
DraftStatus = Literal["auto", "needs_review", "pending", "reviewed", "approved", "rejected", "failed"]


@dataclass(frozen=True, slots=True)
class ParseDraftSaveResult:
    raw_post_id: int
    parse_draft_id: int
    action: Literal["inserted", "updated", "failed"]


@dataclass(frozen=True, slots=True)
class JoyBombDraftSyncResult:
    """The atomic result of synchronizing one JoyBomb raw post's sections."""

    saved: tuple[ParseDraftSaveResult, ...]
    deleted_obsolete: int


@dataclass(frozen=True, slots=True)
class PendingDraftSuitRepairCandidate:
    """A pending draft and its suit candidates for explicit repair review."""

    draft_id: int
    raw_post_id: int
    source: str
    status: str
    content_type_candidate: str | None
    event_name_candidate: str | None
    confidence: float | None
    suit_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftSuitCandidateRecord:
    """One stored suit candidate together with its source section context."""

    parse_draft_suit_id: int
    draft_id: int
    raw_post_id: int
    source: str
    source_post_id: str
    source_title: str | None
    event_name_candidate: str | None
    section_index: int
    section_heading: str | None
    section_hash: str
    splitter_version: str
    section_start_line: int
    section_end_line: int
    suit_name_candidate: str
    confidence: float | None
    section_text: str


def utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat()


def _section_text(content: str, start_line: int, end_line: int) -> str:
    """Return the persisted line range without inspecting another raw post."""
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if start_line < 1 or end_line < start_line:
        return content
    extracted = lines[start_line - 1 : end_line]
    return "\n".join(extracted) if extracted else content


class ParseDraftRepository:
    """Repository for parser drafts and their human review state."""

    def __init__(self, database_path: Path | None = None) -> None:
        self._database_path = database_path
        ensure_database_initialized(database_path)

    def _connect(self) -> sqlite3.Connection:
        return get_connection(self._database_path)

    def get_parse_draft_by_raw_post_id(
        self,
        raw_post_id: int,
        parser_version: str,
        *,
        section_hash: str | None = None,
        splitter_version: str | None = None,
    ) -> dict[str, object] | None:
        connection = self._connect()
        try:
            where = ["raw_post_id = ?", "parser_version = ?"]
            values: list[object] = [raw_post_id, parser_version]
            if section_hash is not None:
                where.append("section_hash = ?")
                values.append(section_hash)
            if splitter_version is not None:
                where.append("splitter_version = ?")
                values.append(splitter_version)
            row = connection.execute(
                "SELECT * FROM parse_drafts WHERE " + " AND ".join(where)
                + " ORDER BY updated_at DESC, section_index LIMIT 1",
                values,
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

    def list_pending_draft_suit_repair_candidates(
        self,
        *,
        source: str,
        statuses: Sequence[str] = ("pending",),
    ) -> list[PendingDraftSuitRepairCandidate]:
        """Return pending source drafts with suit candidates for repair review.

        This method is read-only.  The repair command deliberately uses it to
        require an administrator to select individual high-confidence drafts
        before calling the existing auto-import service.
        """
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT parse_drafts.id,
                       parse_drafts.raw_post_id,
                       raw_posts.source,
                       parse_drafts.status,
                       parse_drafts.content_type_candidate,
                       parse_drafts.event_name_candidate,
                       parse_drafts.confidence
                FROM parse_drafts
                JOIN raw_posts ON raw_posts.id = parse_drafts.raw_post_id
                WHERE raw_posts.source = ?
                  AND parse_drafts.status IN ("""
                + ", ".join("?" for _ in statuses)
                + ")"
                + """
                ORDER BY parse_drafts.id
                """,
                (source, *statuses),
            ).fetchall()
            candidates: list[PendingDraftSuitRepairCandidate] = []
            for row in rows:
                suits = tuple(
                    str(suit_name)
                    for (suit_name,) in connection.execute(
                        """
                        SELECT suit_name_candidate
                        FROM parse_draft_suits
                        WHERE parse_draft_id = ?
                        ORDER BY position, id
                        """,
                        (row[0],),
                    ).fetchall()
                    if str(suit_name).strip()
                )
                if suits:
                    candidates.append(
                        PendingDraftSuitRepairCandidate(
                            draft_id=int(row[0]),
                            raw_post_id=int(row[1]),
                            source=str(row[2]),
                            status=str(row[3]),
                            content_type_candidate=(
                                str(row[4]) if row[4] is not None else None
                            ),
                            event_name_candidate=(
                                str(row[5]) if row[5] is not None else None
                            ),
                            confidence=(float(row[6]) if row[6] is not None else None),
                            suit_names=suits,
                        )
                    )
            return candidates
        finally:
            connection.close()

    def list_draft_suit_candidates(
        self,
        *,
        source: str,
        statuses: Sequence[str] = ("pending",),
        missing_from_knowledge_suits: bool = False,
    ) -> list[DraftSuitCandidateRecord]:
        """Read stored suit candidates with only their own raw-post section text."""
        if not statuses:
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT parse_draft_suits.id,
                       parse_drafts.id,
                       parse_drafts.raw_post_id,
                       raw_posts.source,
                       raw_posts.source_post_id,
                       parse_drafts.title,
                       parse_drafts.event_name_candidate,
                       parse_drafts.section_index,
                       parse_drafts.section_heading,
                       parse_drafts.section_hash,
                       parse_drafts.splitter_version,
                       parse_drafts.section_start_line,
                       parse_drafts.section_end_line,
                       parse_draft_suits.suit_name_candidate,
                       parse_draft_suits.confidence,
                       raw_posts.content
                FROM parse_draft_suits
                JOIN parse_drafts ON parse_drafts.id = parse_draft_suits.parse_draft_id
                JOIN raw_posts ON raw_posts.id = parse_drafts.raw_post_id
                WHERE raw_posts.source = ?
                  AND parse_drafts.status IN ("""
                + ", ".join("?" for _ in statuses)
                + ")"
                + (
                    """
                  AND NOT EXISTS (
                      SELECT 1 FROM suits
                      WHERE lower(trim(suits.name)) = lower(trim(parse_draft_suits.suit_name_candidate))
                  )
                    """
                    if missing_from_knowledge_suits
                    else ""
                )
                + """
                ORDER BY parse_drafts.id, parse_draft_suits.position, parse_draft_suits.id
                """,
                (source, *statuses),
            ).fetchall()
            return [
                DraftSuitCandidateRecord(
                    parse_draft_suit_id=int(row[0]),
                    draft_id=int(row[1]),
                    raw_post_id=int(row[2]),
                    source=str(row[3]),
                    source_post_id=str(row[4]),
                    source_title=str(row[5]) if row[5] is not None else None,
                    event_name_candidate=str(row[6]) if row[6] is not None else None,
                    section_index=int(row[7]),
                    section_heading=str(row[8]) if row[8] is not None else None,
                    section_hash=str(row[9]),
                    splitter_version=str(row[10]),
                    section_start_line=int(row[11]),
                    section_end_line=int(row[12]),
                    suit_name_candidate=str(row[13]),
                    confidence=float(row[14]) if row[14] is not None else None,
                    section_text=_section_text(
                        str(row[15]), int(row[11]), int(row[12])
                    ),
                )
                for row in rows
            ]
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

    def _whole_post_section(self, raw_post_id: int, connection: sqlite3.Connection) -> NoticeSection:
        row = connection.execute("SELECT content, source, source_post_id FROM raw_posts WHERE id = ?", (raw_post_id,)).fetchone()
        if row is None:
            raise ValueError(f"Raw post {raw_post_id} was not found.")
        result = split_notice_sections(str(row[0]), source=str(row[1]), source_post_id=str(row[2]), raw_post_id=raw_post_id)
        if not result.sections:
            raise ValueError(f"Raw post {raw_post_id} has no parsable content.")
        return result.sections[0]

    def _save_parse_draft_in_transaction(
        self,
        connection: sqlite3.Connection,
        raw_post_id: int,
        parser_version: str,
        draft: ParseDraft,
        section: NoticeSection,
        now: str,
    ) -> ParseDraftSaveResult:
        existing = connection.execute(
            "SELECT id FROM parse_drafts WHERE raw_post_id = ? AND section_hash = ? "
            "AND splitter_version = ? AND parser_version = ?",
            (raw_post_id, section.section_hash, section.splitter_version, parser_version),
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
                "INSERT INTO parse_drafts (raw_post_id, parser_version, section_index, section_heading, normalized_heading, "
                "section_start_line, section_end_line, section_hash, splitter_version, status, title, content_type_candidate, "
                "event_name_candidate, official_series_candidate, period_type_candidate, "
                "start_at_candidate, end_at_candidate, player_category_candidate, "
                "acquisition_method_candidate, confidence, parser_notes, error_message, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                (
                    raw_post_id, parser_version, section.section_index, section.heading,
                    section.normalized_heading, section.start_line, section.end_line,
                    section.section_hash, section.splitter_version, *values, now,
                ),
            )
            draft_id = int(cursor.lastrowid)
            action: Literal["inserted", "updated"] = "inserted"
        else:
            draft_id = int(existing[0])
            connection.execute(
                "UPDATE parse_drafts SET status = 'pending', section_index = ?, section_heading = ?, "
                "normalized_heading = ?, section_start_line = ?, section_end_line = ?, title = ?, content_type_candidate = ?, "
                "event_name_candidate = ?, official_series_candidate = ?, "
                "period_type_candidate = ?, start_at_candidate = ?, end_at_candidate = ?, "
                "player_category_candidate = ?, acquisition_method_candidate = ?, "
                "confidence = ?, parser_notes = ?, error_message = NULL, updated_at = ? "
                "WHERE id = ?",
                (
                    section.section_index, section.heading, section.normalized_heading,
                    section.start_line, section.end_line, *values, draft_id,
                ),
            )
            action = "updated"

        self.replace_parse_draft_suits(draft_id, draft.suits, connection)
        return ParseDraftSaveResult(raw_post_id, draft_id, action)

    def save_parse_draft(
        self, raw_post_id: int, parser_version: str, draft: ParseDraft, *, section: NoticeSection | None = None
    ) -> ParseDraftSaveResult:
        """Upsert a draft and candidate suits in a single transaction."""
        now = utc_now_iso8601()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            resolved_section = section or self._whole_post_section(raw_post_id, connection)
            result = self._save_parse_draft_in_transaction(
                connection, raw_post_id, parser_version, draft, resolved_section, now
            )
            connection.execute(
                "UPDATE raw_posts SET parse_status = 'parsed', parse_error = NULL WHERE id = ?",
                (raw_post_id,),
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def sync_joybomb_section_drafts(
        self,
        raw_post_id: int,
        parser_version: str,
        section_drafts: Sequence[tuple[NoticeSection, ParseDraft]],
    ) -> JoyBombDraftSyncResult:
        """Atomically replace one JoyBomb post's current splitter-version drafts.

        Only obsolete hashes in the same raw post/parser/splitter scope are
        removed.  The foreign-key cascade removes their candidate suit rows.
        """
        if not section_drafts:
            raise ValueError("Refusing to synchronize an empty JoyBomb section set.")
        hashes = [section.section_hash for section, _draft in section_drafts]
        if len(set(hashes)) != len(hashes):
            raise ValueError("JoyBomb section hashes must be unique per raw post.")
        splitter_versions = {section.splitter_version for section, _draft in section_drafts}
        if len(splitter_versions) != 1:
            raise ValueError("JoyBomb section drafts must use one splitter version per sync.")

        now = utc_now_iso8601()
        splitter_version = next(iter(splitter_versions))
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            raw_post = connection.execute(
                "SELECT source FROM raw_posts WHERE id = ?", (raw_post_id,)
            ).fetchone()
            if raw_post is None:
                raise ValueError(f"Raw post {raw_post_id} was not found.")
            if raw_post[0] != "joybomb_archive":
                raise ValueError("Section draft synchronization is limited to joybomb_archive.")

            placeholders = ", ".join("?" for _ in hashes)
            obsolete_rows = connection.execute(
                "SELECT id FROM parse_drafts WHERE raw_post_id = ? AND parser_version = ? "
                "AND splitter_version = ? AND section_hash NOT IN (" + placeholders + ")",
                (raw_post_id, parser_version, splitter_version, *hashes),
            ).fetchall()
            obsolete_ids = [int(row[0]) for row in obsolete_rows]
            if obsolete_ids:
                obsolete_placeholders = ", ".join("?" for _ in obsolete_ids)
                connection.execute(
                    "DELETE FROM parse_drafts WHERE id IN (" + obsolete_placeholders + ")",
                    obsolete_ids,
                )

            saved = tuple(
                self._save_parse_draft_in_transaction(
                    connection, raw_post_id, parser_version, draft, section, now
                )
                for section, draft in section_drafts
            )
            connection.execute(
                "UPDATE raw_posts SET parse_status = 'parsed', parse_error = NULL WHERE id = ?",
                (raw_post_id,),
            )
            connection.commit()
            LOGGER.info(
                "Synchronized JoyBomb drafts raw_post_id=%s current=%s deleted_obsolete=%s",
                raw_post_id,
                len(saved),
                len(obsolete_ids),
            )
            return JoyBombDraftSyncResult(saved=saved, deleted_obsolete=len(obsolete_ids))
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_failed_draft(
        self, raw_post_id: int, parser_version: str, error_message: str, *, section: NoticeSection | None = None
    ) -> ParseDraftSaveResult:
        """Record a parser failure without losing the source raw post."""
        now = utc_now_iso8601()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            resolved_section = section or self._whole_post_section(raw_post_id, connection)
            existing = connection.execute(
                "SELECT id FROM parse_drafts WHERE raw_post_id = ? AND section_hash = ? "
                "AND splitter_version = ? AND parser_version = ?",
                (raw_post_id, resolved_section.section_hash, resolved_section.splitter_version, parser_version),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    "INSERT INTO parse_drafts (raw_post_id, parser_version, section_index, section_heading, normalized_heading, "
                    "section_start_line, section_end_line, section_hash, splitter_version, status, error_message, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'failed', ?, ?, ?)",
                    (raw_post_id, parser_version, resolved_section.section_index, resolved_section.heading,
                     resolved_section.normalized_heading, resolved_section.start_line, resolved_section.end_line,
                     resolved_section.section_hash, resolved_section.splitter_version, error_message, now, now),
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
        self, limit: int, raw_post_id: int | None = None, force: bool = False, source: str | None = None
    ) -> list[dict[str, object]]:
        """List raw posts eligible for parser execution, newest first."""
        where: list[str] = []
        values: list[object] = []
        if raw_post_id is not None:
            where.append("id = ?")
            values.append(raw_post_id)
        if not force:
            where.append("parse_status = 'pending'")
        if source is not None:
            where.append("source = ?")
            values.append(source)
        values.append(limit)
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id, content, source_post_id, source, metadata_json FROM raw_posts"
                + (" WHERE " + " AND ".join(where) if where else "")
                + " ORDER BY published_at DESC LIMIT ?",
                values,
            ).fetchall()
            return [
                {
                    "id": row[0],
                    "content": row[1],
                    "source_post_id": row[2],
                    "source": row[3],
                    "metadata_json": row[4],
                }
                for row in rows
            ]
        finally:
            connection.close()
