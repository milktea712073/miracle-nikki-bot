"""Cross-store raw-announcement history search remains read-only and source-neutral."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from announcement.history_archive import ArchivedRawImage, ArchivedRawPost, HistoricalRawArchive
from announcement.history_search import AnnouncementHistorySearchService
from announcement.models import Announcement, CN_OFFICIAL, TW_FACEBOOK_SOURCE, TW_OFFICIAL
from announcement.state_store import AnnouncementStateStore
from bot.announcement_search_view import build_announcement_message_payloads


def make_announcement(
    external_id: str,
    *,
    source: str = TW_OFFICIAL,
    url: str | None = None,
    title: str = "官方公告",
    content: str = "公告正文",
    published_at: datetime | None = None,
    images: tuple[str, ...] = (),
) -> Announcement:
    return Announcement(
        source=source,
        external_id=external_id,
        url=url or f"https://official.example/{source}/{external_id}",
        title=title,
        category=None,
        published_at=published_at,
        content_html=None,
        content_text=content,
        images=images,
    )


def insert_raw_post(
    path: Path,
    raw_post_id: int,
    *,
    source: str = "facebook",
    external_id: str | None = None,
    url: str | None = None,
    content: str = "歷史公告正文",
    published_at: str | None = None,
    title: str | None = None,
    images: tuple[str, ...] = (),
) -> None:
    metadata_json = f'{{"title": "{title}"}}' if title else None
    HistoricalRawArchive(path).synchronize(
        (
            ArchivedRawPost(
                legacy_raw_post_id=raw_post_id, source=source,
                source_post_id=external_id or f"raw-{raw_post_id}",
                url=url or f"https://raw.example/{source}/{raw_post_id}", content=content,
                published_at=published_at, scraped_at=None, updated_at=None,
                parse_status=None, parse_error=None, content_hash=None, metadata_json=metadata_json,
            ),
        ),
        tuple(
            ArchivedRawImage(raw_post_id, image_url, position, "test")
            for position, image_url in enumerate(images)
        ),
        migrated_at="test",
    )


def service(tmp_path: Path) -> tuple[AnnouncementHistorySearchService, AnnouncementStateStore, Path]:
    state_path = tmp_path / "announcement_state.db"
    return (
        AnnouncementHistorySearchService(state_database_path=state_path),
        AnnouncementStateStore(state_path),
        state_path,
    )


def test_search_finds_keyword_only_in_raw_posts_and_uses_metadata_title(tmp_path: Path) -> None:
    history, _store, raw_path = service(tmp_path)
    insert_raw_post(raw_path, 1, content="沒有關鍵字", title="海歌歷史公告")

    result = history.search("海歌").results[0]

    assert result.source_kind == "raw_post"
    assert result.title == "海歌歷史公告"


def test_search_finds_keyword_only_in_active_announcements(tmp_path: Path) -> None:
    history, store, _raw_path = service(tmp_path)
    store.register(make_announcement("state-only", title="現役公告", content="限定關鍵字"), [])

    result = history.search("限定關鍵字").results[0]

    assert result.source_kind == "announcement"
    assert result.external_id == "state-only"


def test_search_merges_announcement_and_raw_results_with_announcement_priority(tmp_path: Path) -> None:
    history, store, raw_path = service(tmp_path)
    url = "https://official.example/post/1"
    store.register(make_announcement("state-1", url=url, title="新版標題", content="新版正文海歌"), [])
    insert_raw_post(raw_path, 1, url=url, title="舊標題", content="舊正文海歌")

    results = history.search("海歌").results

    assert len(results) == 1
    assert results[0].source_kind == "announcement"
    assert results[0].title == "新版標題"
    assert results[0].content_text == "新版正文海歌"


def test_same_source_and_external_id_deduplicates_even_when_urls_differ(tmp_path: Path) -> None:
    history, store, raw_path = service(tmp_path)
    store.register(
        make_announcement(
            "shared-post",
            source=TW_FACEBOOK_SOURCE,
            url="https://www.facebook.com/TwNikkiNikki/posts/shared-state",
            content="公告海歌",
        ),
        [],
    )
    insert_raw_post(
        raw_path,
        1,
        source="facebook",
        external_id="shared-post",
        url="https://m.facebook.com/TwNikkiNikki/posts/shared-raw",
        content="公告海歌",
    )

    assert len(history.search("海歌").results) == 1


def test_raw_post_supplements_missing_announcement_content_and_images(tmp_path: Path) -> None:
    history, store, raw_path = service(tmp_path)
    url = "https://official.example/post/1"
    store.register(make_announcement("state-1", url=url, title="公告海歌", content="", images=()), [])
    insert_raw_post(
        raw_path,
        1,
        url=url,
        title="公告海歌",
        content="較完整的海歌歷史正文",
        images=("https://images.example/raw.png",),
    )

    result = history.search("海歌").results[0]

    assert result.source_kind == "announcement"
    assert result.content_text == "較完整的海歌歷史正文"
    assert result.image_urls == ("https://images.example/raw.png",)


def test_merged_results_sort_by_date_and_apply_one_global_limit(tmp_path: Path) -> None:
    history, store, raw_path = service(tmp_path)
    for index in range(8):
        store.register(
            make_announcement(
                f"state-{index}",
                title="海歌",
                published_at=datetime(2026, 1, index + 1, tzinfo=timezone.utc),
            ),
            [],
        )
    for index in range(8):
        insert_raw_post(
            raw_path,
            index + 1,
            content="海歌",
            published_at=f"2026-01-{index + 9:02d}T00:00:00+00:00",
        )

    page = history.search("海歌")

    assert len(page.results) == 10
    assert [result.source_record_id for result in page.results[:3]] == [8, 7, 6]
    assert page.has_more is True


def test_unbounded_search_returns_all_matching_results_for_discord_pagination(tmp_path: Path) -> None:
    history, store, _raw_path = service(tmp_path)
    for index in range(11):
        store.register(
            make_announcement(
                f"state-{index}",
                title="願之庭",
                published_at=datetime(2026, 1, index + 1, tzinfo=timezone.utc),
            ),
            [],
        )

    page = history.search("願之庭", limit=None)

    assert len(page.results) == 11
    assert page.has_more is False


def test_all_source_search_orders_tw_before_cn_and_sorts_each_region_by_date(tmp_path: Path) -> None:
    history, store, _raw_path = service(tmp_path)
    store.register(
        make_announcement(
            "tw-old",
            title="共同關鍵字",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        [],
    )
    store.register(
        make_announcement(
            "tw-new",
            title="共同關鍵字",
            published_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
        [],
    )
    store.register(make_announcement("tw-undated", title="共同關鍵字"), [])
    store.register(
        make_announcement(
            "cn-old",
            source=CN_OFFICIAL,
            title="共同關鍵字",
            published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        ),
        [],
    )
    store.register(
        make_announcement(
            "cn-new",
            source=CN_OFFICIAL,
            title="共同關鍵字",
            published_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        ),
        [],
    )
    store.register(make_announcement("cn-undated", source=CN_OFFICIAL, title="共同關鍵字"), [])

    all_results = history.search("共同關鍵字", limit=None).results
    tw_results = history.search("共同關鍵字", source=TW_OFFICIAL, limit=None).results
    cn_results = history.search("共同關鍵字", source=CN_OFFICIAL, limit=None).results

    assert [result.external_id for result in all_results] == [
        "tw-new", "tw-old", "tw-undated", "cn-new", "cn-old", "cn-undated",
    ]
    assert [result.external_id for result in tw_results] == ["tw-new", "tw-old", "tw-undated"]
    assert [result.external_id for result in cn_results] == ["cn-new", "cn-old", "cn-undated"]


def test_region_filters_include_recognized_tw_and_cn_raw_posts(tmp_path: Path) -> None:
    history, _store, raw_path = service(tmp_path)
    insert_raw_post(raw_path, 1, source="facebook", content="鑽石活動")
    insert_raw_post(raw_path, 2, source="joybomb_archive", content="鑽石歷史公告")
    insert_raw_post(raw_path, 3, source="cn_official", content="钻石活动")
    insert_raw_post(raw_path, 4, source="unknown", content="鑽石不應納入")

    tw_results = history.search("钻石", source=TW_OFFICIAL).results
    cn_results = history.search("鑽石", source=CN_OFFICIAL).results
    all_results = history.search("鑽石").results

    assert {result.source for result in tw_results} == {"facebook", "joybomb_archive"}
    assert {result.source for result in cn_results} == {"cn_official"}
    assert "unknown" not in {result.source for result in all_results}


def test_raw_legacy_results_support_variant_excerpt_and_multiple_images(tmp_path: Path) -> None:
    history, _store, raw_path = service(tmp_path)
    insert_raw_post(
        raw_path,
        1,
        source="joybomb_archive",
        content=("前言" * 100) + "累计充值" + ("後段" * 100),
        images=("https://images.example/1.png", "https://images.example/2.png"),
    )

    page = history.search("累計")
    payload = build_announcement_message_payloads(page.results[0], owner_user_id=1)[0]

    assert "累计" in payload.embeds[0].description
    assert payload.embeds[0].image.url == "https://images.example/1.png"
    assert payload.view is not None
    payload.view.image_index = 1
    payload.view._update_navigation()
    assert payload.view.embeds()[0].image.url == "https://images.example/2.png"


def test_search_is_available_with_pipeline_disabled(tmp_path: Path) -> None:
    history, _store, raw_path = service(tmp_path)
    insert_raw_post(raw_path, 1, content="海歌歷史公告")

    assert [result.external_id for result in history.search("海歌").results] == ["raw-1"]
