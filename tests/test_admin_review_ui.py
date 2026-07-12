from datetime import datetime, timezone
from types import SimpleNamespace

from bot.admin.checks import is_administrator
from bot.admin.review_data import get_draft_review_data
from bot.admin.review_views import DraftReviewView, create_draft_embed
from crawler.models import Post
from database.parse_draft_repository import ParseDraftRepository
from database.raw_post_repository import RawPostRepository
from parser.announcement_parser import parse_announcement


def test_configured_administrator_user_id_is_allowed(monkeypatch):
    monkeypatch.setenv("DISCORD_ADMIN_USER_IDS", "1001, 2002")
    interaction = SimpleNamespace(user=SimpleNamespace(id=2002))

    assert is_administrator(interaction) is True


def test_unconfigured_non_member_is_not_allowed(monkeypatch):
    monkeypatch.delenv("DISCORD_ADMIN_USER_IDS", raising=False)
    monkeypatch.delenv("DISCORD_ADMIN_ROLE_IDS", raising=False)
    interaction = SimpleNamespace(user=SimpleNamespace(id=2002))

    assert is_administrator(interaction) is False


def test_draft_review_embed_uses_existing_parser_and_review_data(tmp_path):
    database_path = tmp_path / "admin-review.db"
    post = Post(
        post_id="admin-1",
        url="https://example.test/admin-1",
        content=(
            "【復刻】奇迹演唱會 限時復開\n"
            "活動時間：2026年7月13日05:00 – 2026年7月19日23:59\n"
            "可獲得【元氣應援】套裝"
        ),
        published_at=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
        images=[],
    )
    raw_post_id = RawPostRepository(database_path).save_raw_post(post).raw_post_id
    draft_id = ParseDraftRepository(database_path).save_parse_draft(
        raw_post_id, "rules-v1", parse_announcement(post.content)
    ).parse_draft_id

    # The UI service defaults to the project database, so patch it at its boundary.
    from bot.admin import review_data

    original_repository = review_data.KnowledgeRepository
    original_review_repository = review_data.ReviewRepository
    review_data.KnowledgeRepository = lambda: original_repository(database_path)
    review_data.ReviewRepository = lambda: original_review_repository(database_path)
    try:
        data = get_draft_review_data(draft_id)
    finally:
        review_data.KnowledgeRepository = original_repository
        review_data.ReviewRepository = original_review_repository

    embed = create_draft_embed(data)
    assert data.draft["event_name_candidate"] == "奇迹演唱會"
    assert "草稿審核" in embed.title
    assert any(field.name == "Parser 找到的套裝" for field in embed.fields)


def test_edit_only_view_hides_import_action():
    view = DraftReviewView(1, allow_import=False)

    assert all(getattr(item, "label", None) != "驗證並匯入" for item in view.children)
