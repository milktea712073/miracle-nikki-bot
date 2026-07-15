"""Tests for the isolated official website crawler spike."""

from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pytest

from crawler import website_crawler


DETAIL_PAYLOAD = {
    "props": {
        "pageProps": {
            "data": {
                "title": "【活動】測試套裝",
                "publish_time": 1722240000000,
                "content_html": '<p>第一段<img src="https://image/1.jpg"></p><p>第二段<img src="https://image/2.jpg"><img src="https://image/3.jpg"></p>',
            }
        }
    }
}
DETAIL_HTML = f'<html><head><script id="__NEXT_DATA__" type="application/json">{json.dumps(DETAIL_PAYLOAD)}</script></head></html>'


def test_parse_numeric_news_id_accepts_id_and_detail_url() -> None:
    assert website_crawler.parse_numeric_news_id("17024") == "17024"
    assert website_crawler.parse_numeric_news_id("https://nu3.fearlessgames.net/news/17024") == "17024"
    with pytest.raises(website_crawler.WebsiteCrawlerError):
        website_crawler.parse_numeric_news_id("news/not-a-number")


def test_parse_next_data_and_epoch_publish_time() -> None:
    detail = website_crawler.parse_next_data(DETAIL_HTML, url="https://example/news/1")
    assert detail["title"] == "【活動】測試套裝"
    assert website_crawler.parse_publish_time(detail["publish_time"]) == "2024-07-29T08:00:00+00:00"


def test_extract_content_preserves_text_and_image_dom_order() -> None:
    text, images = website_crawler.extract_content(
        '<p>第一段<img src="1.jpg"></p><p>第二段<img src="2.jpg"><img src="3.jpg"></p>'
    )
    assert text == "第一段\n第二段"
    assert images == ["1.jpg", "2.jpg", "3.jpg"]


def test_parse_website_announcement_maps_sections() -> None:
    result = website_crawler.parse_website_announcement(
        {"id": 17024, "title": "列表標題", "section": 1}, DETAIL_HTML
    )
    assert result.source == "website"
    assert result.source_post_id == "17024"
    assert result.section_name == "活動"
    assert result.image_urls == ["https://image/1.jpg", "https://image/2.jpg", "https://image/3.jpg"]


@pytest.mark.parametrize(
    ("section", "expected"),
    [(1, "活動"), (2, "新聞"), (3, "客服"), (11, "系統"), (21, "系統")],
)
def test_section_mapping_uses_official_section_numbers(section: int, expected: str) -> None:
    result = website_crawler.parse_website_announcement(
        {"id": 17024, "title": "列表標題", "section": section}, DETAIL_HTML
    )
    assert result.section_name == expected


def test_missing_detail_fields_are_explicit_errors() -> None:
    with pytest.raises(website_crawler.WebsiteCrawlerError, match="content_html"):
        website_crawler.parse_website_announcement(
            {"id": 1, "title": "列表標題", "section": 2},
            '<script id="__NEXT_DATA__">{"props":{"pageProps":{"data":{"title":"X"}}}}</script>',
        )


def test_crawl_uses_official_list_and_keeps_detail_failures_out_of_data_writes() -> None:
    list_payload = {
        "ret": 0,
        "data": {"total": 2, "data": [{"id": 1, "title": "一", "section": 1}, {"id": 2, "title": "二", "section": 11}]},
    }
    result = website_crawler.crawl_recent_announcements(
        2,
        json_fetcher=lambda _url: list_payload,
        text_fetcher=lambda url: DETAIL_HTML if url.endswith("/1") else "<html></html>",
    )
    assert result.listed_count == 2
    assert [item.source_post_id for item in result.announcements] == ["1"]
    assert result.failures[0].source_post_id == "2"


def test_spike_does_not_write_raw_posts_or_announcement_jobs(tmp_path: Path) -> None:
    database_path = tmp_path / "database.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE raw_posts (id INTEGER PRIMARY KEY, source TEXT, source_post_id TEXT);
        CREATE TABLE announcement_jobs (id INTEGER PRIMARY KEY, raw_post_id INTEGER);
        INSERT INTO raw_posts VALUES (1, 'facebook', 'existing');
        INSERT INTO announcement_jobs VALUES (1, 1);
        """
    )
    connection.commit()
    connection.close()

    result = website_crawler.crawl_recent_announcements(
        1,
        json_fetcher=lambda _url: {"ret": 0, "data": {"total": 1, "data": [{"id": 1, "title": "一", "section": 1}]}},
        text_fetcher=lambda _url: DETAIL_HTML,
    )
    website_crawler.write_report(result, tmp_path / "report.json")

    verify = sqlite3.connect(database_path)
    assert verify.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 1
    assert verify.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 1
    verify.close()


def test_comparison_is_read_only_and_only_uses_title_and_date(tmp_path: Path) -> None:
    database_path = tmp_path / "database.db"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE raw_posts (id INTEGER PRIMARY KEY, source TEXT, url TEXT, content TEXT, published_at TEXT, scraped_at TEXT)")
    connection.execute(
        "INSERT INTO raw_posts VALUES (?, ?, ?, ?, ?, ?)",
        (
            1,
            "facebook",
            "https://facebook/post",
            "【活動】測試套裝\n內文",
            "2024-07-29T08:00:00+00:00",
            "2024-07-29T08:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()
    announcement = website_crawler.parse_website_announcement({"id": 1, "title": "x", "section": 1}, DETAIL_HTML)

    comparison = website_crawler.compare_with_facebook([announcement], database_path)
    assert comparison["available"] is True
    assert comparison["items"][0]["status"] == "matched"
    verify = sqlite3.connect(database_path)
    assert verify.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 1
    verify.close()
