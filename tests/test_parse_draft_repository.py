from datetime import datetime, timezone

import pytest

from crawler.models import Post
from database.parse_draft_repository import ParseDraftRepository
from database.raw_post_repository import RawPostRepository
from parser.announcement_parser import parse_announcement


@pytest.fixture
def repositories(tmp_path):
    path = tmp_path / "drafts.db"
    raw_repository = RawPostRepository(path)
    draft_repository = ParseDraftRepository(path)
    post = Post(
        post_id="raw-1",
        url="https://example.test/raw-1",
        content=(
            "\u3010\u5fa9\u523b\u3011\u5947\u8ff9\u6f14\u5531\u6703 \u9650\u6642\u5fa9\u958b\n"
            "\u6d3b\u52d5\u6642\u9593\uff1a2026\u5e747\u670813\u65e505:00 \u2013 2026\u5e747\u670819\u65e523:59\n"
            "\u53ef\u7372\u5f97\u3010\u5143\u6c23\u61c9\u63f4\u3011\u3001\u3010\u7d55\u5c0d\u6416\u6efe\u3011\u5957\u88dd"
        ),
        published_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
        images=[],
    )
    raw_id = raw_repository.save_raw_post(post).raw_post_id
    return raw_repository, draft_repository, raw_id, post


def test_save_draft_marks_raw_post_parsed_and_preserves_suit_order(repositories):
    raw_repository, draft_repository, raw_id, post = repositories
    draft_repository.save_parse_draft(raw_id, "rules-v1", parse_announcement(post.content))

    draft = draft_repository.get_parse_draft_by_raw_post_id(raw_id, "rules-v1")
    raw = raw_repository.get_raw_post_by_source_id(post.post_id)
    assert raw["parse_status"] == "parsed"
    assert draft["status"] == "pending"
    assert draft["suits"] == ["\u5143\u6c23\u61c9\u63f4", "\u7d55\u5c0d\u6416\u6efe"]


def test_rerun_updates_draft_and_replaces_suit_order(repositories):
    _, draft_repository, raw_id, post = repositories
    first = draft_repository.save_parse_draft(raw_id, "rules-v1", parse_announcement(post.content))
    changed = parse_announcement(
        "\u3010\u5fa9\u523b\u3011\u5947\u8ff9\u6f14\u5531\u6703\n"
        "\u53ef\u7372\u5f97\u3010\u7d55\u5c0d\u6416\u6efe\u3011\u3001\u3010\u5143\u6c23\u61c9\u63f4\u3011\u5957\u88dd"
    )
    second = draft_repository.save_parse_draft(raw_id, "rules-v1", changed)

    draft = draft_repository.get_parse_draft_by_raw_post_id(raw_id, "rules-v1")
    assert first.action == "inserted"
    assert second.action == "updated"
    assert draft["suits"] == ["\u7d55\u5c0d\u6416\u6efe", "\u5143\u6c23\u61c9\u63f4"]


def test_failed_draft_marks_raw_post_failed(repositories):
    raw_repository, draft_repository, raw_id, post = repositories
    draft_repository.save_failed_draft(raw_id, "rules-v1", "parser failure")

    draft = draft_repository.get_parse_draft_by_raw_post_id(raw_id, "rules-v1")
    raw = raw_repository.get_raw_post_by_source_id(post.post_id)
    assert draft["status"] == "failed"
    assert draft["error_message"] == "parser failure"
    assert raw["parse_status"] == "failed"


def test_rerun_preserves_review_notes(repositories):
    _, draft_repository, raw_id, post = repositories
    saved = draft_repository.save_parse_draft(raw_id, "rules-v1", parse_announcement(post.content))
    draft_repository.update_review_status(saved.parse_draft_id, "reviewed", "keep this note")
    draft_repository.save_parse_draft(raw_id, "rules-v1", parse_announcement(post.content))

    draft = draft_repository.get_parse_draft_by_raw_post_id(raw_id, "rules-v1")
    assert draft["review_notes"] == "keep this note"
