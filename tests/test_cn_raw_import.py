"""Raw-only CN official crawler and state-archive import coverage."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import requests

from announcement.models import Announcement, CN_OFFICIAL
from announcement.raw_import import OfficialRawAnnouncementImporter
from announcement.state_store import AnnouncementStateStore
from crawler import cn_official_crawler
from scripts.data import fetch_cn_announcements


CN_LIST = """
<ul id="newsList" class="news-list">
  <li><p class="info"><span>2026-07-20</span></p><a class="title" href="/news/1001.shtml">【活动】第一篇</a></li>
  <li><p class="info"><span>2026-07-19</span></p><a class="title" href="/news/1002.shtml">【公告】第二篇</a></li>
</ul>
"""
CN_DETAIL = """
<div class="content"><div class="hd"><p class="info"><span>2026-07-20 11:20:12</span></p></div>
<div class="context"><p>完整正文第一段。</p><p>第二段<br>條列內容</p>
<img src="/images/one.png"><img src="/images/two.png"><img src="/images/one.png"></div></div>
"""


def _list_document(
    *items: tuple[str, str],
    next_page: int | None = None,
    next_href: str | None = None,
) -> str:
    rows = "".join(
        f'<li><p class="info"><span>2026-07-20</span></p>'
        f'<a class="title" href="/news/{external_id}.shtml">【公告】{title}</a></li>'
        for external_id, title in items
    )
    target = next_href or (f"list_{next_page}.shtml" if next_page else None)
    pagination = f'<div class="guid"><a class="next" href="{target}">下一頁</a></div>' if target else ""
    return f'<ul id="newsList" class="news-list">{rows}</ul>{pagination}'


class FakeResponse:
    def __init__(self, *, url: str, text: str, encoding: str = "utf-8") -> None:
        self.url = url
        self.text = text
        self.content = text.encode(encoding)
        self.encoding = encoding
        self.apparent_encoding = encoding

    def raise_for_status(self) -> None:
        return None


def test_cn_fetch_skips_one_bad_detail_and_keeps_other_notices() -> None:
    list_url = cn_official_crawler.LIST_URL_TEMPLATE.format(page=1)
    valid_url = "https://qjnn.qq.com/news/1001.shtml"
    invalid_url = "https://qjnn.qq.com/news/1002.shtml"
    responses = {
        list_url: FakeResponse(url=list_url, text=CN_LIST),
        valid_url: FakeResponse(url=valid_url, text=CN_DETAIL),
        invalid_url: FakeResponse(url=invalid_url, text="<html>broken</html>"),
    }
    progress: list[tuple[int, int, str]] = []

    result = cn_official_crawler.fetch_recent_announcements_with_failures(
        2,
        get=responses.__getitem__,
        on_detail_start=lambda index, total, item: progress.append((index, total, item.external_id)),
    )

    assert progress == [(1, 2, "1001"), (2, 2, "1002")]
    assert [item.external_id for item in result.announcements] == ["1001"]
    assert result.announcements[0].content_text == "完整正文第一段。\n第二段\n條列內容"
    assert result.announcements[0].images == (
        "https://qjnn.qq.com/images/one.png",
        "https://qjnn.qq.com/images/two.png",
    )
    assert result.failures[0].external_id == "1002"


def test_cn_all_fetch_pages_until_empty_and_deduplicates_list_items() -> None:
    page_one = cn_official_crawler.LIST_URL_TEMPLATE.format(page=1)
    page_two = cn_official_crawler.LIST_URL_TEMPLATE.format(page=2)
    page_three = cn_official_crawler.LIST_URL_TEMPLATE.format(page=3)
    responses = {
        page_one: FakeResponse(url=page_one, text=_list_document(("1003", "三"), ("1002", "二"), next_page=2)),
        page_two: FakeResponse(url=page_two, text=_list_document(("1002", "二"), ("1001", "一"), next_page=3)),
        page_three: FakeResponse(url=page_three, text=_list_document()),
        "https://qjnn.qq.com/news/1001.shtml": FakeResponse(url="https://qjnn.qq.com/news/1001.shtml", text=CN_DETAIL),
        "https://qjnn.qq.com/news/1002.shtml": FakeResponse(url="https://qjnn.qq.com/news/1002.shtml", text=CN_DETAIL),
        "https://qjnn.qq.com/news/1003.shtml": FakeResponse(url="https://qjnn.qq.com/news/1003.shtml", text=CN_DETAIL),
    }
    pages: list[tuple[int, int, int]] = []

    result = cn_official_crawler.fetch_all_announcements_with_failures(
        get=responses.__getitem__,
        on_list_page=lambda page, cumulative, new: pages.append((page, cumulative, new)),
    )

    assert [notice.external_id for notice in result.announcements] == ["1003", "1002", "1001"]
    assert result.pages_fetched == 3
    assert result.listed_count == 3
    assert result.stopped_reason == "empty_page"
    assert pages == [(1, 2, 2), (2, 3, 1), (3, 3, 0)]


def test_cn_all_fetch_respects_max_page_safety_limit() -> None:
    page_one = cn_official_crawler.LIST_URL_TEMPLATE.format(page=1)
    responses = {
        page_one: FakeResponse(url=page_one, text=_list_document(("1001", "一"), next_page=2)),
        "https://qjnn.qq.com/news/1001.shtml": FakeResponse(url="https://qjnn.qq.com/news/1001.shtml", text=CN_DETAIL),
    }

    result = cn_official_crawler.fetch_all_announcements_with_failures(get=responses.__getitem__, max_pages=1)

    assert result.pages_fetched == 1
    assert result.stopped_reason == "max_pages"
    assert [notice.external_id for notice in result.announcements] == ["1001"]


def test_cn_all_fetch_follows_mixed_numeric_and_guid_next_urls() -> None:
    base = "https://qjnn.qq.com/webplat/info/news_version3/11785/23142/23143/m14776/"
    page_urls = [f"{base}list_{page}.shtml" for page in (1, 2, 3)] + [f"{base}list_n101.shtml", f"{base}list_n100.shtml"]
    responses = {
        page_urls[0]: FakeResponse(url=page_urls[0], text=_list_document(("1005", "五"), next_page=2)),
        page_urls[1]: FakeResponse(url=page_urls[1], text=_list_document(("1004", "四"), next_page=3)),
        page_urls[2]: FakeResponse(url=page_urls[2], text=_list_document(("1003", "三"), next_href="list_n101.shtml")),
        page_urls[3]: FakeResponse(url=page_urls[3], text=_list_document(("1002", "二"), next_href="list_n100.shtml")),
        page_urls[4]: FakeResponse(url=page_urls[4], text=_list_document(("1001", "一"))),
    }
    responses.update(
        {
            f"https://qjnn.qq.com/news/{external_id}.shtml": FakeResponse(
                url=f"https://qjnn.qq.com/news/{external_id}.shtml", text=CN_DETAIL
            )
            for external_id in ("1001", "1002", "1003", "1004", "1005")
        }
    )

    result = cn_official_crawler.fetch_all_announcements_with_failures(get=responses.__getitem__)

    assert [notice.external_id for notice in result.announcements] == ["1005", "1004", "1003", "1002", "1001"]
    assert result.pages_fetched == 5
    assert result.stopped_reason == "no_next_page"


def test_cn_all_fetch_stops_before_revisiting_a_guid_next_url() -> None:
    page_one = cn_official_crawler.LIST_URL_TEMPLATE.format(page=1)
    guid_page = page_one.replace("list_1.shtml", "list_n101.shtml")
    responses = {
        page_one: FakeResponse(url=page_one, text=_list_document(("1002", "二"), next_href="list_n101.shtml")),
        guid_page: FakeResponse(url=guid_page, text=_list_document(("1001", "一"), next_href="list_1.shtml")),
        "https://qjnn.qq.com/news/1001.shtml": FakeResponse(url="https://qjnn.qq.com/news/1001.shtml", text=CN_DETAIL),
        "https://qjnn.qq.com/news/1002.shtml": FakeResponse(url="https://qjnn.qq.com/news/1002.shtml", text=CN_DETAIL),
    }

    result = cn_official_crawler.fetch_all_announcements_with_failures(get=responses.__getitem__)

    assert result.pages_fetched == 2
    assert result.stopped_reason == "visited_next_url"


def test_cn_all_fetch_stops_when_next_link_is_missing() -> None:
    page_one = cn_official_crawler.LIST_URL_TEMPLATE.format(page=1)
    responses = {
        page_one: FakeResponse(url=page_one, text=_list_document(("1001", "一"))),
        "https://qjnn.qq.com/news/1001.shtml": FakeResponse(url="https://qjnn.qq.com/news/1001.shtml", text=CN_DETAIL),
    }

    result = cn_official_crawler.fetch_all_announcements_with_failures(get=responses.__getitem__)

    assert result.pages_fetched == 1
    assert result.stopped_reason == "no_next_page"


def test_cn_request_retries_transient_list_failure(monkeypatch) -> None:
    page_one = cn_official_crawler.LIST_URL_TEMPLATE.format(page=1)
    calls = 0

    def get(url: str) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise requests.ConnectionError("temporary")
        if url == page_one:
            return FakeResponse(url=page_one, text=CN_LIST)
        return FakeResponse(url=url, text=CN_DETAIL)

    monkeypatch.setattr(cn_official_crawler.time, "sleep", lambda _seconds: None)
    result = cn_official_crawler.fetch_recent_announcements_with_failures(1, get=get)

    assert calls == 3
    assert [notice.external_id for notice in result.announcements] == ["1001"]


def test_cn_raw_import_preserves_metadata_images_and_is_idempotent(tmp_path: Path) -> None:
    state_path = tmp_path / "announcement_state.db"
    AnnouncementStateStore(state_path)
    announcement = Announcement(
        source=CN_OFFICIAL,
        external_id="1001",
        url="https://qjnn.qq.com/news/1001.shtml",
        title="【活动】第一篇",
        category="活动",
        published_at=datetime(2026, 7, 20, 11, 20, 12, tzinfo=cn_official_crawler.CHINA_TIMEZONE),
        content_html="<div class='context'><p>完整正文</p></div>",
        content_text="完整正文",
        images=(
            "https://qjnn.qq.com/images/one.png",
            "https://qjnn.qq.com/images/two.png",
            "https://qjnn.qq.com/images/one.png",
        ),
    )
    importer = OfficialRawAnnouncementImporter(state_path)

    first = importer.synchronize([announcement])
    second = importer.synchronize([announcement])

    assert first.storage.inserted_raw_posts == 1
    assert first.storage.inserted_images == 2
    assert second.storage.inserted_raw_posts == 0
    assert second.storage.existing_raw_posts == 1
    connection = sqlite3.connect(state_path)
    try:
        raw = connection.execute(
            "SELECT id, source, source_post_id, content, published_at, metadata_json FROM raw_posts"
        ).fetchone()
        assert raw is not None
        assert raw[1:4] == (CN_OFFICIAL, "1001", "完整正文")
        assert raw[4] == "2026-07-20T11:20:12+08:00"
        metadata = json.loads(raw[5])
        assert metadata["title"] == "【活动】第一篇"
        assert metadata["content_html"] == "<div class='context'><p>完整正文</p></div>"
        images = connection.execute(
            "SELECT image_url FROM raw_post_images WHERE raw_post_id = ? ORDER BY position", (raw[0],)
        ).fetchall()
        assert images == [
            ("https://qjnn.qq.com/images/one.png",),
            ("https://qjnn.qq.com/images/two.png",),
        ]
        assert connection.execute("SELECT COUNT(*) FROM announcement_deliveries").fetchone()[0] == 0
    finally:
        connection.close()


def test_cn_raw_fetch_cli_path_writes_only_raw_archive(monkeypatch, tmp_path: Path) -> None:
    announcement = Announcement(
        source=CN_OFFICIAL,
        external_id="1001",
        url="https://qjnn.qq.com/news/1001.shtml",
        title="第一篇",
        category=None,
        published_at=None,
        content_html="<p>正文</p>",
        content_text="正文",
        images=(),
    )
    crawl_result = cn_official_crawler.CNFetchResult([announcement], [])
    monkeypatch.setattr(
        fetch_cn_announcements,
        "fetch_recent_announcements_with_failures",
        lambda _limit, on_detail_start: crawl_result,
    )

    _crawl_result, import_result = fetch_cn_announcements.fetch_and_store_cn_announcements(
        1,
        state_database_path=tmp_path / "announcement_state.db",
    )

    assert import_result.storage.inserted_raw_posts == 1


def test_cn_raw_fetch_cli_all_path_uses_full_crawler_and_writes_only_raw_archive(monkeypatch, tmp_path: Path) -> None:
    crawl_result = cn_official_crawler.CNFetchResult([], [], pages_fetched=2, listed_count=0, stopped_reason="empty_page")
    calls: list[int] = []
    monkeypatch.setattr(
        fetch_cn_announcements,
        "fetch_all_announcements_with_failures",
        lambda **kwargs: calls.append(kwargs["max_pages"]) or crawl_result,
    )

    _crawl_result, import_result = fetch_cn_announcements.fetch_and_store_cn_announcements(
        20,
        state_database_path=tmp_path / "announcement_state.db",
        fetch_all=True,
        max_pages=7,
    )

    assert calls == [7]
    assert import_result.storage.inserted_raw_posts == 0
