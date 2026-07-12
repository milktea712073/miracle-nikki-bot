from datetime import datetime, timezone

from crawler.models import Post
from database.import_service import import_parse_draft
from database.knowledge_query_repository import KnowledgeQueryRepository
from database.parse_draft_repository import ParseDraftRepository
from database.raw_post_repository import RawPostRepository
from database.review_repository import ReviewRepository
from parser.announcement_parser import parse_announcement


def imported_event_database(tmp_path):
    database_path = tmp_path / "knowledge-query.db"
    post = Post(
        post_id="query-1",
        url="https://example.test/query-1",
        content=(
            "【復刻】奇迹演唱會 限時復開\n"
            "活動時間：2026年7月13日05:00 – 2026年7月19日23:59\n"
            "可獲得【元氣應援】、【絕對搖滾】套裝"
        ),
        published_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
        images=[],
    )
    raw_post_id = RawPostRepository(database_path).save_raw_post(post).raw_post_id
    draft_id = ParseDraftRepository(database_path).save_parse_draft(
        raw_post_id, "rules-v1", parse_announcement(post.content)
    ).parse_draft_id
    review_repository = ReviewRepository(database_path)
    event_type_id = review_repository.get_reference_options("event_types")[0][0]
    acquisition_method_id = review_repository.get_reference_options(
        "acquisition_methods"
    )[0][0]
    review_repository.save_review(
        draft_id,
        event_type_id=event_type_id,
        acquisition_method_id=acquisition_method_id,
        event_cost_text="約4200鑽",
    )
    review_repository.update_draft_status(draft_id, "approved")
    import_parse_draft(draft_id, database_path)
    return database_path


def test_get_event_by_name_returns_approved_knowledge_base_data(tmp_path):
    repository = KnowledgeQueryRepository(imported_event_database(tmp_path))

    event = repository.get_event_by_name("奇迹演唱會")

    assert event is not None
    assert event.periods[0].period_type == "rerun"
    assert [suit.name for suit in event.suits] == ["元氣應援", "絕對搖滾"]
    assert event.event_total_cost == "約4200鑽"


def test_get_suit_by_name_returns_its_event(tmp_path):
    repository = KnowledgeQueryRepository(imported_event_database(tmp_path))

    suit = repository.get_suit_by_name("元氣應援")

    assert suit is not None
    assert suit.events[0].event_name == "奇迹演唱會"


def test_search_names_returns_matching_records(tmp_path):
    repository = KnowledgeQueryRepository(imported_event_database(tmp_path))

    assert repository.search_event_names("演唱") == ["奇迹演唱會"]
    assert repository.search_suit_names("搖滾") == ["絕對搖滾"]
