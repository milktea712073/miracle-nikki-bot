"""Automatic, parser-only import of usable announcement candidates."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Collection

from database.knowledge_repository import KnowledgeRepository


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AutoImportResult:
    """Result of attempting to expose parser data in the knowledge base."""

    draft_id: int
    status: str
    event_id: int | None
    suit_ids: list[int]


def auto_import_parse_draft(
    draft_id: int,
    database_path: Path | None = None,
    *,
    eligible_suit_names: Collection[str] | None = None,
) -> AutoImportResult:
    """Upsert parser candidates without overwriting verified knowledge records.

    ``eligible_suit_names`` lets a maintenance workflow import only a reviewed
    subset of an unchanged draft.  Normal parser execution continues to import
    every stored candidate by leaving it as ``None``.
    """
    repository = KnowledgeRepository(database_path)
    connection = repository.connect()
    try:
        draft = repository.get_parse_draft(connection, draft_id)
        if draft is None:
            raise ValueError(f"Parse draft {draft_id} does not exist.")

        content_type = str(draft.get("content_type_candidate") or "other")
        suit_names = [str(name).strip() for name in draft["suits"] if str(name).strip()]
        if eligible_suit_names is not None:
            allowed = {str(name).strip() for name in eligible_suit_names if str(name).strip()}
            suit_names = [name for name in suit_names if name in allowed]
        # Compatibility for legacy drafts created before content classification.
        if content_type == "other" and suit_names:
            content_type = "suit_event"
        event_name = str(draft["event_name_candidate"] or "").strip() or None
        # A parser may reliably find suits while being unable to normalize the
        # announcement title. Keep that title as a provisional event link rather
        # than leaving otherwise usable suits disconnected.
        if event_name is None and suit_names:
            event_name = str(draft["title"] or "").strip() or None
        if content_type in {"welfare", "wallpaper", "system", "notice"}:
            connection.execute("BEGIN")
            connection.execute(
                "UPDATE parse_drafts SET status = 'auto', updated_at = updated_at WHERE id = ?",
                (draft_id,),
            )
            connection.commit()
            LOGGER.info("Draft %s is %s, so it is retained without an event import.", draft_id, content_type)
            return AutoImportResult(draft_id, "auto", None, [])
        if content_type == "other" and not suit_names:
            connection.execute("BEGIN")
            connection.execute(
                "UPDATE parse_drafts SET status = 'needs_review', updated_at = updated_at WHERE id = ?",
                (draft_id,),
            )
            connection.commit()
            return AutoImportResult(draft_id, "needs_review", None, [])
        if event_name is None:
            connection.execute("BEGIN")
            connection.execute(
                "UPDATE parse_drafts SET status = 'needs_review', updated_at = updated_at WHERE id = ?",
                (draft_id,),
            )
            connection.commit()
            LOGGER.warning("Draft %s has no event or suit candidate; needs review.", draft_id)
            return AutoImportResult(draft_id, "needs_review", None, [])

        raw_post_id = int(draft["raw_post_id"])
        source_row = connection.execute(
            "SELECT source FROM raw_posts WHERE id = ?", (raw_post_id,)
        ).fetchone()
        source = str(source_row[0]) if source_row is not None else ""
        # JoyBomb notices can contain several independent, explicitly split
        # activities.  Their event identity therefore includes the section
        # fingerprint.  Existing Facebook and website imports retain their
        # established one-event-per-raw-post identity.
        section_hash = str(draft["section_hash"]) if source == "joybomb_archive" else None
        splitter_version = (
            str(draft["splitter_version"]) if source == "joybomb_archive" else None
        )
        connection.execute("BEGIN")
        event_id: int | None = None
        if event_name is not None:
            event_id = repository.upsert_auto_event(
                connection,
                event_name,
                draft["official_series_candidate"],
                draft["title"],
                raw_post_id,
                content_type,
                section_hash,
                splitter_version,
            )
            period_type = str(draft["period_type_candidate"] or "unknown")
            start_at = draft["start_at_candidate"]
            end_at = draft["end_at_candidate"]
            if repository.find_event_period(connection, event_id, period_type, start_at, end_at) is None:
                repository.create_auto_event_period(
                    connection,
                    event_id,
                    period_type,
                    start_at,
                    end_at,
                    draft["parser_notes"],
                    raw_post_id,
                )

        suit_ids: list[int] = []
        for position, suit_name in enumerate(dict.fromkeys(suit_names)):
            suit_id = repository.upsert_auto_suit(connection, suit_name, raw_post_id)
            suit_ids.append(suit_id)
            if event_id is not None and repository.find_event_suit(connection, event_id, suit_id) is None:
                repository.create_auto_event_suit(
                    connection, event_id, suit_id, position, raw_post_id
                )

        result_status = "auto"
        if content_type == "suit_event" and not suit_ids:
            repository.mark_event_needs_review(connection, event_id)
            result_status = "needs_review"

        connection.execute(
            "UPDATE parse_drafts SET status = ?, updated_at = updated_at WHERE id = ?",
            (result_status, draft_id),
        )
        connection.commit()
        LOGGER.info("Auto-imported draft %s as event=%s suits=%s", draft_id, event_id, suit_ids)
        return AutoImportResult(draft_id, result_status, event_id, suit_ids)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
