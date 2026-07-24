"""Taiwan Fearless official raw-only crawler and import coverage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from announcement.history_search import AnnouncementHistorySearchService
from announcement.models import TW_OFFICIAL
from announcement.raw_import import OfficialRawAnnouncementImporter
from announcement.state_store import AnnouncementStateStore
from crawler import tw_fearless_official_crawler
from scripts.data import fetch_tw_fearless_announcements


def _detail_html(title: str, publish_time: int, content_html: str) -> str:
    payload = {"props": {"pageProps": {"data": {"title": title, "publish_time": publish_time, "content_html": content_html}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'


def _page_payload(entries: list[dict[str, object]], total: int) -> dict[str, object]:
    return {"ret": 0, "data": {"total": total, "data": entries}}


def test_tw_fearless_crawl_pages_and_preserves_raw_metadata_images() -> None:
    rows = [
        {"id": 1003, "title": "活動", "section": 1},
        {"id": 1002, "title": "系統", "section": 11},
        {"id": 1001, "title": "新聞", "section": 2},
    ]
    calls: list[str] = []

    def json_fetcher(url: str) -> object:
        calls.append(url)
        if "offset=0" in url:
            return _page_payload(rows[:2], 3)
        return _page_payload(rows[2:], 3)

    details = {
        "1003": _detail_html("活動標題", 1722240000000, '<p>正文<img src="/one.png"><img data-src="/two.png"></p>'),
        "1002": _detail_html("系統標題", 1722240000000, "<p>系統正文</p>"),
        "1001": _detail_html("新聞標題", 1722240000000, "<p>新聞正文</p>"),
    }
    result = tw_fearless_official_crawler.fetch_recent_announcements_with_failures(
        3,
        page_size=2,
        json_fetcher=json_fetcher,
        text_fetcher=lambda url: details[url.rsplit("/", 1)[-1]],
    )

    assert len(calls) == 2
    assert result.pages_fetched == 2
    assert result.list_total == 3
    assert result.failures == []
    first = result.announcements[0]
    assert first.source == "tw_fearless_official"
    assert first.external_id == "1003"
    assert first.category == "活動"
    assert first.metadata["section"] == 1
    assert first.metadata["section_name"] == "活動"
    assert first.images == (
        "https://nu3.fearlessgames.net/one.png",
        "https://nu3.fearlessgames.net/two.png",
    )


def test_tw_fearless_category_filter_uses_section_values_and_detail_failures_continue() -> None:
    rows = [
        {"id": 1003, "title": "活動", "section": 1},
        {"id": 1002, "title": "客服", "section": 3},
        {"id": 1001, "title": "系統", "section": 11},
    ]
    result = tw_fearless_official_crawler.fetch_recent_announcements_with_failures(
        2,
        category="support",
        json_fetcher=lambda _url: _page_payload(rows, 3),
        text_fetcher=lambda url: "<html>broken</html>" if url.endswith("/1002") else _detail_html("系統", 1722240000000, "<p>正文</p>"),
    )

    assert [item.external_id for item in result.announcements] == ["1001"]
    assert result.failures[0].external_id == "1002"


def test_tw_fearless_raw_import_is_idempotent_and_searchable_as_taiwan(tmp_path: Path) -> None:
    state_path = tmp_path / "announcement_state.db"
    AnnouncementStateStore(state_path)
    announcement = tw_fearless_official_crawler.fetch_recent_announcements_with_failures(
        1,
        json_fetcher=lambda _url: _page_payload([{"id": 1001, "title": "願之庭公告", "section": 1}], 1),
        text_fetcher=lambda _url: _detail_html("願之庭公告", 1722240000000, '<p>完整願之庭正文<img src="https://image/one.png"></p>'),
    ).announcements[0]
    importer = OfficialRawAnnouncementImporter(state_path)
    first = importer.synchronize([announcement])
    second = importer.synchronize([announcement])

    assert first.storage.inserted_raw_posts == 1
    assert second.storage.inserted_raw_posts == 0
    connection = sqlite3.connect(state_path)
    try:
        raw = connection.execute("SELECT source, source_post_id, metadata_json FROM raw_posts").fetchone()
        assert raw[:2] == ("tw_fearless_official", "1001")
        assert json.loads(raw[2])["section"] == 1
        assert connection.execute("SELECT COUNT(*) FROM raw_post_images").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM announcement_deliveries").fetchone()[0] == 0
    finally:
        connection.close()
    page = AnnouncementHistorySearchService(state_database_path=state_path).search("願之庭", source=TW_OFFICIAL)
    assert page.results[0].region == "tw"
    assert page.results[0].source == "tw_fearless_official"


def test_tw_fearless_cli_path_writes_only_raw_archive(monkeypatch, tmp_path: Path) -> None:
    result = tw_fearless_official_crawler.TWFearlessFetchResult([], [], 0, 0, 0)
    monkeypatch.setattr(
        fetch_tw_fearless_announcements,
        "fetch_recent_announcements_with_failures",
        lambda _limit, **_kwargs: result,
    )

    _crawl, imported = fetch_tw_fearless_announcements.fetch_and_store_tw_fearless_announcements(
        1, category="all", state_database_path=tmp_path / "announcement_state.db"
    )
    assert imported.storage.inserted_raw_posts == 0
