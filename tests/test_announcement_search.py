"""Keyword history search uses the existing v2 announcement state database."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import bot.main as bot_main
import pytest

from bot.announcement_search_view import build_announcement_message_payloads
from announcement.history_archive import ArchivedRawPost, HistoricalRawArchive
from announcement.history_search import AnnouncementHistorySearchService
from announcement.models import Announcement, CN_OFFICIAL, TW_FACEBOOK_SOURCE, TW_OFFICIAL
import announcement.search as announcement_search
from announcement.search import build_search_excerpt, keyword_search_variants
from announcement.search_models import AnnouncementSearchPage, AnnouncementSearchResult
from announcement.state_store import AnnouncementStateStore


def make_announcement(
    external_id: str,
    *,
    source: str = TW_OFFICIAL,
    title: str = "官方公告",
    content: str = "公告正文",
    published_at: datetime | None = None,
    images: tuple[str, ...] = (),
) -> Announcement:
    return Announcement(
        source=source,
        external_id=external_id,
        url=f"https://official.example/{source}/{external_id}",
        title=title,
        category=None,
        published_at=published_at,
        content_html=None,
        content_text=content,
        images=images,
    )


def store_with_announcements(tmp_path: Path) -> AnnouncementStateStore:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(
        make_announcement(
            "tw-title",
            title="福袋限時上架",
            published_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ),
        [],
    )
    store.register(
        make_announcement(
            "tw-body",
            title="商城更新",
            content="本期福袋內容與優惠說明。",
            published_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        ),
        [],
    )
    store.register(
        make_announcement(
            "cn-title",
            source=CN_OFFICIAL,
            title="福袋活动开启",
            published_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        ),
        [],
    )
    return store


def test_search_matches_titles_and_bodies(tmp_path: Path) -> None:
    store = store_with_announcements(tmp_path)

    results = store.search_announcements("福袋").results

    assert [result.external_id for result in results] == ["cn-title", "tw-body", "tw-title"]


def test_search_filters_by_official_source(tmp_path: Path) -> None:
    store = store_with_announcements(tmp_path)

    assert [result.external_id for result in store.search_announcements("福袋", source=TW_OFFICIAL).results] == [
        "tw-body",
        "tw-title",
    ]
    assert [result.external_id for result in store.search_announcements("福袋", source=CN_OFFICIAL).results] == [
        "cn-title"
    ]


def test_all_source_search_includes_retained_facebook_archive_records(tmp_path: Path) -> None:
    store = store_with_announcements(tmp_path)
    store.register(
        make_announcement(
            "legacy-facebook",
            source=TW_FACEBOOK_SOURCE,
            title="福袋 Facebook 舊公告",
            published_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
        ),
        [],
    )

    assert "legacy-facebook" in [result.external_id for result in store.search_announcements("福袋").results]


def test_search_returns_no_result_and_rejects_blank_keywords(tmp_path: Path) -> None:
    store = store_with_announcements(tmp_path)

    assert store.search_announcements("不存在").results == ()
    with pytest.raises(ValueError, match="blank"):
        store.search_announcements("   ")


def test_search_returns_newest_ten_and_reports_more_results(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    for index in range(12):
        store.register(
            make_announcement(
                str(index),
                title=f"測試公告 {index}",
                published_at=datetime(2026, 1, index + 1, tzinfo=timezone.utc),
            ),
            [],
        )

    page = store.search_announcements("測試公告")

    assert [result.external_id for result in page.results] == [str(index) for index in range(11, 1, -1)]
    assert page.has_more is True


def test_search_treats_sql_wildcards_as_literal_text(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(
        make_announcement("literal", title="100%_優惠公告", content="內容"),
        [],
    )
    store.register(
        make_announcement("other", title="100XX優惠公告", content="內容"),
        [],
    )

    assert [result.external_id for result in store.search_announcements("100%_").results] == ["literal"]


def test_traditional_keyword_matches_simplified_title(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(make_announcement("cn-title", source=CN_OFFICIAL, title="累计充值馈赠"), [])

    assert [result.external_id for result in store.search_announcements("累計").results] == ["cn-title"]


def test_traditional_keyword_matches_simplified_content(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(make_announcement("cn-body", source=CN_OFFICIAL, title="公告", content="累计充值活动"), [])

    assert [result.external_id for result in store.search_announcements("累計").results] == ["cn-body"]


def test_simplified_keyword_matches_traditional_title_and_content(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(make_announcement("tw-title", title="鑽石優惠"), [])
    store.register(make_announcement("tw-body", title="公告", content="鑽石加碼贈送"), [])

    assert [result.external_id for result in store.search_announcements("钻石").results] == ["tw-body", "tw-title"]


def test_search_excerpt_locates_a_simplified_body_match_for_traditional_keyword() -> None:
    excerpt = build_search_excerpt(("前言" * 100) + "累计充值" + ("後段" * 100), "累計")

    assert excerpt is not None
    assert "累计" in excerpt
    assert excerpt.startswith("…")


def test_unchanged_variants_do_not_duplicate_sql_conditions(monkeypatch) -> None:
    class UnchangedConverter:
        def convert(self, value: str) -> str:
            return value

    monkeypatch.setattr(announcement_search, "_get_opencc_converters", lambda: (UnchangedConverter(), UnchangedConverter()))

    assert keyword_search_variants("ABC123") == ("ABC123",)


def test_traditional_simplified_search_keeps_sql_wildcards_literal(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(make_announcement("literal", title=r"累计%_\\活动"), [])
    store.register(make_announcement("other", title=r"累计XX活动"), [])

    assert [result.external_id for result in store.search_announcements(r"累計%_\\").results] == ["literal"]


def test_english_and_numeric_search_behavior_is_unchanged(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(make_announcement("english", title="Version 13.2 update"), [])

    assert [result.external_id for result in store.search_announcements("13.2").results] == ["english"]


def test_search_falls_back_to_literal_keyword_when_opencc_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(make_announcement("traditional", title="累計登入獎勵"), [])
    monkeypatch.setattr(announcement_search, "_get_opencc_converters", lambda: ())

    assert [result.external_id for result in store.search_announcements("累計").results] == ["traditional"]
    assert store.search_announcements("累计").results == ()


def test_variant_search_preserves_source_filter_and_limit(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    for index in range(12):
        store.register(
            make_announcement(
                f"tw-{index}",
                title="鑽石活動",
                published_at=datetime(2026, 1, index + 1, tzinfo=timezone.utc),
            ),
            [],
        )
    store.register(make_announcement("cn", source=CN_OFFICIAL, title="钻石活动"), [])

    page = store.search_announcements("钻石", source=TW_OFFICIAL)

    assert [result.external_id for result in page.results] == [f"tw-{index}" for index in range(11, 1, -1)]
    assert page.has_more is True


def test_search_uses_full_content_not_the_rendered_excerpt(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    content = "opening " + ("x" * 500) + " tail-keyword"
    store.register(make_announcement("tail", title="unrelated", content=content), [])

    results = store.search_announcements("tail-keyword").results

    assert [result.external_id for result in results] == ["tail"]
    assert results[0].content_text == content


def test_search_finds_a_content_only_middle_match(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(
        make_announcement("middle", title="unrelated", content=("before " * 80) + "needle" + (" after" * 80)),
        [],
    )

    result = store.search_announcements("needle").results[0]

    assert result.external_id == "middle"
    assert "needle" in result.content_text


def test_search_excerpt_centres_a_body_match_instead_of_always_using_the_opening() -> None:
    content = "前言" * 100 + "關鍵字" + "後段" * 100

    excerpt = build_search_excerpt(content, "關鍵字")

    assert excerpt is not None
    assert "關鍵字" in excerpt
    assert excerpt.startswith("…")
    assert excerpt.endswith("…")
    assert not excerpt.startswith("前言前言前言前言")


def test_search_excerpt_uses_opening_for_title_only_matches_and_skips_empty_content() -> None:
    assert build_search_excerpt("  第一段\n\n第二段  ", "不在正文") == "第一段 第二段"
    assert build_search_excerpt(" \n ", "關鍵字") is None


def test_search_result_embed_uses_the_first_valid_saved_announcement_image(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(
        make_announcement(
            "with-images",
            title="圖片公告",
            content="圖片公告正文",
            images=("not-a-url", "https://images.example.test/first.png", "https://images.example.test/second.png"),
        ),
        [],
    )

    payload = build_announcement_message_payloads(store.search_announcements("圖片公告").results[0], owner_user_id=1)[0]

    assert payload.embeds[0].image.url == "https://images.example.test/first.png"


def test_search_result_embeds_show_multiple_distinct_images_up_to_the_per_notice_cap(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    images = (
        "https://images.example.test/1.png",
        "https://images.example.test/2.png",
        "https://images.example.test/2.png",
        "ftp://images.example.test/invalid.png",
        "https://images.example.test/3.png",
        "https://images.example.test/4.png",
        "https://images.example.test/5.png",
    )
    store.register(make_announcement("many-images", title="many images", images=images), [])

    payload = build_announcement_message_payloads(store.search_announcements("many").results[0], owner_user_id=1)[0]

    assert payload.embeds[0].image.url == "https://images.example.test/1.png"
    assert payload.embeds[0].footer.text.endswith("圖片 1 / 5")


def test_search_result_embed_without_images_keeps_text_result(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(make_announcement("without-images", title="純文字公告", content="純文字公告正文"), [])

    payload = build_announcement_message_payloads(store.search_announcements("純文字公告").results[0], owner_user_id=1)[0]

    assert payload.embeds[0].image.url is None
    assert "純文字公告正文" in payload.embeds[0].description


def test_search_image_url_problem_does_not_hide_other_results(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(make_announcement("invalid", title="圖片測試 A", images=("invalid-url",)), [])
    store.register(
        make_announcement("valid", title="圖片測試 B", images=("https://images.example.test/valid.png",)),
        [],
    )

    page = store.search_announcements("圖片測試")
    payloads = {
        result.title: build_announcement_message_payloads(result, owner_user_id=1)[0]
        for result in page.results
    }
    assert payloads["圖片測試 A"].embeds[0].image.url is None
    assert payloads["圖片測試 B"].embeds[0].image.url == "https://images.example.test/valid.png"


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False
        self.messages: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def defer(self, **_kwargs: object) -> None:
        self.deferred = True

    async def send_message(self, *args: object, **kwargs: object) -> None:
        self.messages.append((args, kwargs))


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.sent_messages: list[object] = []

    async def send(self, *args: object, **kwargs: object) -> object:
        self.messages.append((args, kwargs))
        message = SimpleNamespace()
        self.sent_messages.append(message)
        return message


class FakeInteraction:
    def __init__(self, channel_id: int = 101) -> None:
        self.channel_id = channel_id
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.user = SimpleNamespace(id=1)


async def allow_query(_interaction: object) -> bool:
    return True


def test_search_command_works_when_announcement_pipeline_is_disabled(monkeypatch, tmp_path: Path) -> None:
    store = store_with_announcements(tmp_path)
    store.register(
        make_announcement(
            "tw-image",
            title="福袋圖片公告",
            content="福袋圖片正文",
            images=("https://images.example.test/announcement.png",),
        ),
        [],
    )
    interaction = FakeInteraction()
    monkeypatch.setattr(bot_main, "ENABLE_ANNOUNCEMENT_PIPELINE", False)
    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: True)
    monkeypatch.setattr(
        bot_main,
        "AnnouncementHistorySearchService",
        lambda: SimpleNamespace(search=store.search_announcements),
    )
    asyncio.run(bot_main.announcement_search_command.callback(interaction, "福袋", "all"))

    assert interaction.response.deferred is True
    assert len(interaction.followup.messages) == 1
    payload = interaction.followup.messages[0][1]
    assert "embed" in payload
    assert "view" in payload
    assert "找到 4 筆公告" in payload["embed"].title
    assert payload["embed"].image.url is None


def test_search_command_exposes_fixed_announcement_source_choices() -> None:
    parameter = next(
        parameter
        for parameter in bot_main.announcement_search_command.parameters
        if parameter.name == "source"
    )

    assert parameter.display_name == "公告來源"
    assert parameter.default == "all"
    assert [(choice.name, choice.value) for choice in parameter.choices] == [
        ("全部", "all"),
        ("台服", "tw"),
        ("陸服", "cn"),
    ]


def test_search_command_requests_unbounded_results_for_result_list_pagination(monkeypatch) -> None:
    interaction = FakeInteraction()
    observed_limits: list[int | None] = []
    results = tuple(
        AnnouncementSearchResult(
            source_kind="announcement",
            source_record_id=index,
            source="tw_official",
            region="tw",
            external_id=str(index),
            title=f"願之庭 {index}",
            canonical_url=f"https://official.example/{index}",
            published_at="2026-07-23T00:00:00+00:00",
            content_text="願之庭公告",
            image_urls=(),
        )
        for index in range(11)
    )

    def search(*_args: object, **kwargs: object) -> AnnouncementSearchPage:
        observed_limits.append(kwargs["limit"])
        return AnnouncementSearchPage(results=results, has_more=False)

    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: True)
    monkeypatch.setattr(
        bot_main,
        "AnnouncementHistorySearchService",
        lambda: SimpleNamespace(search=search),
    )

    asyncio.run(bot_main.announcement_search_command.callback(interaction, "願之庭", "all"))

    assert observed_limits == [None]
    view = interaction.followup.messages[0][1]["view"]
    assert view.total_pages == 2


def test_search_command_rejects_unknown_source_value(monkeypatch) -> None:
    interaction = FakeInteraction()
    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: True)

    asyncio.run(bot_main.announcement_search_command.callback(interaction, "福袋", "other"))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [
        (("請選擇有效的公告伺服器篩選條件。",), {"ephemeral": True})
    ]


def test_search_command_rejects_blank_keyword(monkeypatch) -> None:
    interaction = FakeInteraction()
    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: True)

    asyncio.run(bot_main.announcement_search_command.callback(interaction, "   ", "all"))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [
        (("請輸入公告搜尋關鍵字。",), {"ephemeral": True})
    ]


def test_search_command_returns_matching_archived_raw_post(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "announcement_state.db"
    AnnouncementStateStore(state_path)
    HistoricalRawArchive(state_path).synchronize(
        (
            ArchivedRawPost(
                legacy_raw_post_id=1,
                source="joybomb_archive",
                source_post_id="1:example",
                url="https://archive.example/notice/1",
                content="小屋願之庭限時開放。",
                published_at="2020-01-01T00:00:00+00:00",
                scraped_at=None,
                updated_at=None,
                parse_status=None,
                parse_error=None,
                content_hash=None,
                metadata_json='{"title": "歷史公告"}',
            ),
        ),
        (),
        migrated_at="test",
    )
    interaction = FakeInteraction()
    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: True)
    monkeypatch.setattr(
        bot_main,
        "AnnouncementHistorySearchService",
        lambda: AnnouncementHistorySearchService(state_database_path=state_path),
    )

    asyncio.run(bot_main.announcement_search_command.callback(interaction, "願之庭", "all"))

    assert interaction.response.deferred is True
    assert len(interaction.followup.messages) == 1
    assert "小屋**願之庭**限時開放。" in interaction.followup.messages[0][1]["embeds"][0].description


def test_search_command_reports_no_results(monkeypatch, tmp_path: Path) -> None:
    interaction = FakeInteraction()
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: True)
    monkeypatch.setattr(
        bot_main,
        "AnnouncementHistorySearchService",
        lambda: SimpleNamespace(search=store.search_announcements),
    )
    asyncio.run(bot_main.announcement_search_command.callback(interaction, "不存在", "all"))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [
        (("找不到包含「不存在」的公告。",), {"ephemeral": True})
    ]


def test_search_command_uses_existing_query_channel_restriction(monkeypatch) -> None:
    interaction = FakeInteraction(channel_id=999)
    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: False)

    asyncio.run(bot_main.announcement_search_command.callback(interaction, "福袋", "all"))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [
        (("請到指定的查詢頻道使用此指令。",), {"ephemeral": True})
    ]


def test_search_command_logs_and_reports_rendering_error(monkeypatch, tmp_path: Path, caplog) -> None:
    interaction = FakeInteraction()
    store = store_with_announcements(tmp_path)
    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: True)
    monkeypatch.setattr(
        bot_main,
        "AnnouncementHistorySearchService",
        lambda: SimpleNamespace(search=store.search_announcements),
    )

    original_send = interaction.followup.send
    failed = False

    async def fail_once(*args: object, **kwargs: object) -> object:
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("render failed")
        return await original_send(*args, **kwargs)

    monkeypatch.setattr(interaction.followup, "send", fail_once)
    asyncio.run(bot_main.announcement_search_command.callback(interaction, "福袋", "all"))

    assert interaction.response.deferred is True
    assert "Announcement-search result-list rendering failed" in caplog.text
    assert "RuntimeError: render failed" in caplog.text
    assert interaction.followup.messages == [
        (("公告搜尋結果呈現失敗，請稍後再試。",), {"ephemeral": True})
    ]


@pytest.mark.parametrize("keyword", ["願之庭", "海歌", "永夜"])
def test_search_command_renders_known_historical_keywords_without_processing_error(monkeypatch, keyword: str) -> None:
    interaction = FakeInteraction()
    result = AnnouncementSearchResult(
        source_kind="raw_post",
        source_record_id=1,
        source="joybomb_archive",
        region="tw",
        external_id=f"legacy-{keyword}",
        title=f"{keyword} 公告",
        canonical_url=f"https://archive.example/{keyword}",
        published_at="2020-01-01T00:00:00+00:00",
        content_text=f"這是包含 {keyword} 的完整歷史公告正文。",
        image_urls=(),
    )
    page = AnnouncementSearchPage(results=(result,), has_more=False)
    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: True)
    monkeypatch.setattr(
        bot_main,
        "AnnouncementHistorySearchService",
        lambda: SimpleNamespace(search=lambda *_args, **_kwargs: page),
    )

    asyncio.run(bot_main.announcement_search_command.callback(interaction, keyword, "all"))

    assert interaction.response.deferred is True
    assert len(interaction.followup.messages) == 1
    embeds = interaction.followup.messages[0][1]["embeds"]
    assert embeds[0].title == f"**{keyword}** 公告"
    assert f"**{keyword}** 的完整歷史公告正文。" in embeds[0].description
    assert "view" not in interaction.followup.messages[0][1]
    assert all(
        args != ("公告搜尋結果呈現失敗，請稍後再試。",)
        for args, _kwargs in interaction.followup.messages
    )


def test_search_command_omits_view_for_single_image(monkeypatch) -> None:
    interaction = FakeInteraction()
    result = AnnouncementSearchResult(
        source_kind="announcement",
        source_record_id=1,
        source="tw_official",
        region="tw",
        external_id="single-image",
        title="單圖公告",
        canonical_url="https://official.example/single-image",
        published_at="2026-07-23T00:00:00+00:00",
        content_text="單張圖片仍可正常顯示公告。",
        image_urls=("https://images.example/single.png",),
    )
    page = AnnouncementSearchPage(results=(result,), has_more=False)
    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: True)
    monkeypatch.setattr(
        bot_main,
        "AnnouncementHistorySearchService",
        lambda: SimpleNamespace(search=lambda *_args, **_kwargs: page),
    )

    asyncio.run(bot_main.announcement_search_command.callback(interaction, "單圖", "all"))

    send_kwargs = interaction.followup.messages[0][1]
    assert send_kwargs["embeds"][0].image.url == "https://images.example/single.png"
    assert "view" not in send_kwargs


def test_search_command_passes_and_binds_view_for_multiple_images(monkeypatch) -> None:
    interaction = FakeInteraction()
    result = AnnouncementSearchResult(
        source_kind="announcement",
        source_record_id=1,
        source="tw_official",
        region="tw",
        external_id="multiple-images",
        title="多圖公告",
        canonical_url="https://official.example/multiple-images",
        published_at="2026-07-23T00:00:00+00:00",
        content_text="多張圖片可翻頁。",
        image_urls=("https://images.example/one.png", "https://images.example/two.png"),
    )
    page = AnnouncementSearchPage(results=(result,), has_more=False)
    monkeypatch.setattr(bot_main, "is_query_channel", lambda _channel_id: True)
    monkeypatch.setattr(
        bot_main,
        "AnnouncementHistorySearchService",
        lambda: SimpleNamespace(search=lambda *_args, **_kwargs: page),
    )

    asyncio.run(bot_main.announcement_search_command.callback(interaction, "多圖", "all"))

    send_kwargs = interaction.followup.messages[0][1]
    assert send_kwargs["view"] is not None
    assert send_kwargs["view"].message is interaction.followup.sent_messages[0]
