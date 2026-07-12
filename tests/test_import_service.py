from datetime import datetime, timezone

import pytest

from crawler.models import Post
from database.import_service import DraftImportError, import_parse_draft
from database.knowledge_repository import KnowledgeRepository
from database.parse_draft_repository import ParseDraftRepository
from database.raw_post_repository import RawPostRepository
from database.review_repository import ReviewRepository
from parser.announcement_parser import parse_announcement


@pytest.fixture
def approved_draft(tmp_path):
    database_path = tmp_path / "knowledge.db"
    raw_repository = RawPostRepository(database_path)
    draft_repository = ParseDraftRepository(database_path)
    post = Post(
        post_id="import-1",
        url="https://example.test/import-1",
        content=(
            "\u3010\u5fa9\u523b\u3011\u5947\u8ff9\u6f14\u5531\u6703 \u9650\u6642\u5fa9\u958b\n"
            "\u6d3b\u52d5\u6642\u9593\uff1a2026\u5e747\u670813\u65e505:00 \u2013 2026\u5e747\u670819\u65e523:59\n"
            "\u53ef\u7372\u5f97\u3010\u5143\u6c23\u61c9\u63f4\u3011\u3001\u3010\u7d55\u5c0d\u6416\u6efe\u3011\u5957\u88dd"
        ),
        published_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
        images=[],
    )
    raw_id = raw_repository.save_raw_post(post).raw_post_id
    saved = draft_repository.save_parse_draft(raw_id, "rules-v1", parse_announcement(post.content))
    return database_path, draft_repository, saved.parse_draft_id


def table_count(database_path, table_name):
    connection = KnowledgeRepository(database_path).connect()
    try:
        return connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    finally:
        connection.close()


def approve_review(database_path, draft_id):
    repository = ReviewRepository(database_path)
    review = repository.get_or_create_review(draft_id)
    event_type_id = repository.get_reference_options("event_types")[0][0]
    acquisition_method_id = repository.get_reference_options("acquisition_methods")[0][0]
    repository.save_review(draft_id, event_type_id=event_type_id, acquisition_method_id=acquisition_method_id)
    repository.update_draft_status(draft_id, "approved")


def test_non_approved_draft_cannot_import(approved_draft):
    database_path, _, draft_id = approved_draft

    with pytest.raises(DraftImportError, match="must be approved"):
        import_parse_draft(draft_id, database_path)
    assert table_count(database_path, "events") == 0


def test_approved_draft_creates_complete_knowledge_base_data(approved_draft):
    database_path, draft_repository, draft_id = approved_draft
    approve_review(database_path, draft_id)

    result = import_parse_draft(draft_id, database_path)
    assert result.event_id > 0
    assert result.event_period_id is not None
    assert len(result.suit_ids) == 2
    assert table_count(database_path, "events") == 1
    assert table_count(database_path, "event_periods") == 1
    assert table_count(database_path, "suits") == 2
    assert table_count(database_path, "event_suits") == 2
    assert table_count(database_path, "cost_records") == 0


def test_reimport_reuses_event_suits_and_period(approved_draft):
    database_path, draft_repository, draft_id = approved_draft
    approve_review(database_path, draft_id)
    first = import_parse_draft(draft_id, database_path)
    second = import_parse_draft(draft_id, database_path)

    assert first.event_id == second.event_id
    assert table_count(database_path, "events") == 1
    assert table_count(database_path, "event_periods") == 1
    assert table_count(database_path, "suits") == 2
    assert table_count(database_path, "event_suits") == 2


def test_import_rolls_back_when_event_suit_insert_fails(approved_draft, monkeypatch):
    database_path, draft_repository, draft_id = approved_draft
    approve_review(database_path, draft_id)

    def fail_event_suit(*args, **kwargs):
        raise RuntimeError("event suit failure")

    monkeypatch.setattr(KnowledgeRepository, "create_event_suit", fail_event_suit)
    with pytest.raises(RuntimeError, match="event suit failure"):
        import_parse_draft(draft_id, database_path)

    assert table_count(database_path, "events") == 0
    assert table_count(database_path, "suits") == 0
