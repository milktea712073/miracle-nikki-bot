"""Import approved parse drafts into the formal knowledge base."""

import logging
from dataclasses import dataclass
from pathlib import Path

from database.knowledge_repository import KnowledgeRepository


LOGGER = logging.getLogger(__name__)


class DraftImportError(RuntimeError):
    """Raised when a draft cannot be imported into the knowledge base."""


@dataclass(frozen=True, slots=True)
class ImportResult:
    draft_id: int
    event_id: int
    event_period_id: int | None
    suit_ids: list[int]


def import_parse_draft(draft_id: int, database_path: Path | None = None) -> ImportResult:
    """Import an approved draft atomically, without creating cost records."""
    repository = KnowledgeRepository(database_path)
    connection = repository.connect()
    try:
        draft = repository.get_parse_draft(connection, draft_id)
        if draft is None:
            raise DraftImportError(f"Parse draft {draft_id} does not exist.")
        if draft["status"] != "approved":
            raise DraftImportError(f"Parse draft {draft_id} must be approved before import.")
        event_name = draft["event_name_candidate"]
        review = repository.get_draft_review(connection, draft_id)
        if review is None:
            raise DraftImportError(f"Parse draft {draft_id} has no human review.")
        event_name = review["confirmed_event_name"]
        if not event_name:
            raise DraftImportError(f"Parse draft {draft_id} has no event name candidate.")

        connection.execute("BEGIN")
        event_id = repository.find_event(connection, str(event_name))
        if event_id is None:
            event_id = repository.create_event(
                connection,
                str(event_name),
                review["official_series"],
                review["event_type_id"],
                draft["title"],
            )
        else:
            repository.update_event(connection, event_id, review["official_series"], review["event_type_id"], draft["title"])

        period_type = str(draft["period_type_candidate"] or "unknown")
        start_at = draft["start_at_candidate"]
        end_at = draft["end_at_candidate"]
        period_id = repository.find_event_period(
            connection, event_id, period_type, start_at, end_at
        )
        if period_id is None:
            period_id = repository.create_event_period(
                connection, event_id, period_type, start_at, end_at, draft["review_notes"]
            )

        suit_ids: list[int] = []
        for suit_name, display_order, is_live2d, cost_text, notes in review["suits"]:
            suit_id = repository.find_suit(connection, str(suit_name))
            if suit_id is None:
                suit_id = repository.create_suit(connection, str(suit_name))
            if is_live2d:
                connection.execute("UPDATE suits SET is_live2d = 1 WHERE id = ?", (suit_id,))
            suit_ids.append(suit_id)
            if repository.find_event_suit(connection, event_id, suit_id) is None:
                repository.create_event_suit(
                    connection, event_id, suit_id, review["acquisition_method_id"], display_order, notes
                )
            if cost_text:
                repository.upsert_cost_record(connection, event_id, suit_id, "single_suit", cost_text, notes)
        if review["event_cost_text"]:
            repository.upsert_cost_record(connection, event_id, None, "event_total", review["event_cost_text"], review["review_notes"])
        if review["live2d_cost_text"]:
            repository.upsert_cost_record(connection, event_id, None, "live2d", review["live2d_cost_text"], review["review_notes"])

        repository.mark_auto_import_verified(connection, event_id, suit_ids)

        connection.commit()
        LOGGER.info("Imported approved parse draft %s into event %s", draft_id, event_id)
        return ImportResult(draft_id, event_id, period_id, suit_ids)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
