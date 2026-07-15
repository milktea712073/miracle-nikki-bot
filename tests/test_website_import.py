"""Integration coverage for importing official website posts without Discord jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from crawler.models import Post
from crawler.website_crawler import WebsiteAnnouncement, WebsiteCrawlResult
from database.announcement_job_repository import AnnouncementJobRepository
from database.database import get_connection, init_database
from database.raw_post_repository import RawPostRepository
from scripts.data.fetch_website_posts import fetch_and_save_website_posts
from scripts.data.parse_raw_posts import parse_pending_raw_posts


UTC = timezone.utc


def website_announcement() -> WebsiteAnnouncement:
    return WebsiteAnnouncement(
        source_post_id="17322",
        url="https://nu3.fearlessgames.net/news/17322",
        title="【全新】網站活動",
        section=1,
        section_name="活動",
        publish_time="2026-07-16T04:00:00+00:00",
        content_text="活動時間：2026年7月16日05:00 - 2026年7月25日23:59\n可獲得套裝【網站之星】",
        content_html="<p>活動內容</p><img src=\"https://images.example/website.png\">",
        image_urls=["https://images.example/website.png"],
    )


def test_website_import_inserts_source_metadata_images_and_no_announcement_job(tmp_path: Path) -> None:
    database_path = tmp_path / "website.db"
    init_database(database_path)
    AnnouncementJobRepository(database_path).initialize_from_existing_raw_posts()

    result = fetch_and_save_website_posts(
        30,
        database_path,
        crawler=lambda _limit: WebsiteCrawlResult([website_announcement()], [], 1),
    )

    assert result.fetched_count == 1
    assert result.storage.inserted == 1
    row = RawPostRepository(database_path).get_raw_post_by_source_id("17322", source="website")
    assert row is not None
    assert row["source"] == "website"
    assert row["images"] == ["https://images.example/website.png"]
    assert row["metadata"] == {
        "section": "activity",
        "section_id": 1,
        "section_name": "活動",
        "content_type_candidate": "event",
        "title": "【全新】網站活動",
    }
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
    finally:
        connection.close()


def test_website_and_facebook_share_parser_and_auto_import_without_identity_collision(tmp_path: Path) -> None:
    database_path = tmp_path / "all-sources.db"
    repository = RawPostRepository(database_path)
    website_result = fetch_and_save_website_posts(
        1,
        database_path,
        crawler=lambda _limit: WebsiteCrawlResult([website_announcement()], [], 1),
    )
    repository.save_raw_post(
        Post(
            post_id="facebook-1",
            url="https://www.facebook.com/TwNikkiNikki/posts/facebook-1",
            content="【復刻】Facebook活動\n2026/07/20 05:00 - 2026/07/26 23:59\n套裝【Facebook之星】",
            published_at=datetime(2026, 7, 19, 4, 0, tzinfo=UTC),
            images=[],
        ),
        enqueue_announcement=False,
    )

    parsed = parse_pending_raw_posts(2, database_path)

    assert website_result.storage.inserted == 1
    assert parsed.succeeded == 2
    connection = get_connection(database_path)
    try:
        rows = connection.execute(
            "SELECT r.source, d.content_type_candidate FROM parse_drafts d "
            "JOIN raw_posts r ON r.id = d.raw_post_id ORDER BY r.source"
        ).fetchall()
        assert rows == [("facebook", "suit_event"), ("website", "event")]
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM suits").fetchone()[0] == 2
    finally:
        connection.close()


def test_same_source_post_id_is_distinct_between_facebook_and_website(tmp_path: Path) -> None:
    repository = RawPostRepository(tmp_path / "source-identity.db")
    repository.save_raw_post(
        Post("42", "https://www.facebook.com/TwNikkiNikki/posts/42", "Facebook", None, [])
    )
    repository.save_raw_post(
        Post("42", "https://nu3.fearlessgames.net/news/42", "Website", None, [], source="website")
    )

    assert repository.raw_post_exists("42", source="facebook")
    assert repository.raw_post_exists("42", source="website")
