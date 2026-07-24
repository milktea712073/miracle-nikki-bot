"""Tests for the complete per-notice announcement search renderer."""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from types import SimpleNamespace

import bot.announcement_search_view as search_view
from announcement.search_models import AnnouncementSearchResult
from bot.announcement_search_view import (
    AnnouncementImageView,
    AnnouncementSearchResultView,
    SEARCH_VIEW_TIMEOUT_SECONDS,
    build_announcement_message_payloads,
    build_search_results_embed,
    highlight_search_terms,
    split_announcement_content,
)


def make_result(
    record_id: int,
    *,
    source_kind: str = "announcement",
    source: str = "tw_official",
    region: str | None = "tw",
    content: str = "First paragraph.\n\nSecond paragraph.",
    images: tuple[str, ...] = (),
    published_at: str | None = "2026-07-23T08:00:00+00:00",
) -> AnnouncementSearchResult:
    return AnnouncementSearchResult(
        source_kind=source_kind,
        source_record_id=record_id,
        source=source,
        region=region,
        external_id=str(record_id),
        title=f"Notice {record_id}",
        canonical_url=f"https://official.example/{record_id}",
        published_at=published_at,
        content_text=content,
        image_urls=images,
    )


class FakeResponse:
    def __init__(self) -> None:
        self.edits: list[dict[str, object]] = []
        self.messages: list[tuple[str, dict[str, object]]] = []
        self.done = False

    async def edit_message(self, **kwargs: object) -> None:
        self.done = True
        self.edits.append(kwargs)

    async def send_message(self, content: str, **kwargs: object) -> None:
        self.done = True
        self.messages.append((content, kwargs))

    def is_done(self) -> bool:
        return self.done


class FakeInteraction:
    def __init__(self, user_id: int = 1) -> None:
        self.user = SimpleNamespace(id=user_id)
        self.response = FakeResponse()


class FakeMessage:
    def __init__(self) -> None:
        self.edits: list[dict[str, object]] = []

    async def edit(self, **kwargs: object) -> None:
        self.edits.append(kwargs)


class FakeSelectionResponse:
    def __init__(self) -> None:
        self.deferred = False
        self.done = False
        self.messages: list[tuple[str, dict[str, object]]] = []

    async def defer(self, **_kwargs: object) -> None:
        self.deferred = True
        self.done = True

    async def send_message(self, content: str, **kwargs: object) -> None:
        self.done = True
        self.messages.append((content, kwargs))

    def is_done(self) -> bool:
        return self.done


class FakeSelectionFollowup:
    def __init__(self) -> None:
        self.messages: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.sent_messages: list[object] = []

    async def send(self, *args: object, **kwargs: object) -> object:
        self.messages.append((args, kwargs))
        message = SimpleNamespace()
        self.sent_messages.append(message)
        return message


class FakeSelectionInteraction:
    def __init__(self, user_id: int = 1) -> None:
        self.user = SimpleNamespace(id=user_id)
        self.response = FakeSelectionResponse()
        self.followup = FakeSelectionFollowup()


def test_short_notice_is_complete_in_one_message_without_notice_pagination() -> None:
    payloads = build_announcement_message_payloads(make_result(1), owner_user_id=1)

    assert len(payloads) == 1
    assert len(payloads[0].embeds) == 1
    assert "First paragraph.\n\nSecond paragraph." in payloads[0].embeds[0].description
    assert payloads[0].view is None
    assert all("公告 X / N" not in (embed.footer.text or "") for embed in payloads[0].embeds)


def test_highlight_search_terms_marks_single_and_repeated_matches() -> None:
    assert highlight_search_terms("願之庭 假日露營地，願之庭復刻。", "願之庭", ("願之庭",)) == (
        "**願之庭** 假日露營地，**願之庭**復刻。"
    )


def test_highlight_search_terms_marks_traditional_and_simplified_variants() -> None:
    assert highlight_search_terms("願之庭與愿之庭皆可命中。", "願之庭", ("願之庭", "愿之庭")) == (
        "**願之庭**與**愿之庭**皆可命中。"
    )


def test_highlight_search_terms_preserves_existing_bold_and_urls() -> None:
    text = "**願之庭** https://example.test/願之庭?query=願之庭 願之庭"

    assert highlight_search_terms(text, "願之庭", ("願之庭",)) == (
        "**願之庭** https://example.test/願之庭?query=願之庭 **願之庭**"
    )


def test_highlight_search_terms_leaves_unmatched_text_unchanged() -> None:
    text = "沒有任何命中的公告內容。\n保留原本換行與標點！"

    assert highlight_search_terms(text, "願之庭", ("願之庭", "愿之庭")) == text


def test_complete_payload_highlights_title_and_content_without_changing_links() -> None:
    result = make_result(
        1,
        content="願之庭資訊：https://example.test/願之庭\n愿之庭也會命中。",
    )
    result = replace(result, title="願之庭公告")

    payload = build_announcement_message_payloads(
        result,
        owner_user_id=1,
        highlight_terms=("願之庭", "愿之庭"),
    )[0]

    assert payload.embeds[0].title == "**願之庭**公告"
    assert "**願之庭**資訊" in payload.embeds[0].description
    assert "https://example.test/願之庭" in payload.embeds[0].description
    assert "https://example.test/**願之庭**" not in payload.embeds[0].description
    assert "**愿之庭**也會命中。" in payload.embeds[0].description


def test_three_results_produce_three_independent_notice_messages() -> None:
    payloads = [
        build_announcement_message_payloads(make_result(record_id), owner_user_id=1)
        for record_id in (1, 2, 3)
    ]

    assert [len(item) for item in payloads] == [1, 1, 1]
    assert [item[0].embeds[0].title for item in payloads] == ["Notice 1", "Notice 2", "Notice 3"]


def test_long_notice_splits_at_paragraph_or_sentence_boundaries() -> None:
    content = ("Sentence one. " * 900) + "\n\n" + ("Sentence two. " * 900)
    chunks = split_announcement_content(content)
    payloads = build_announcement_message_payloads(make_result(1, content=content), owner_user_id=1)

    assert len(chunks) > 1
    assert all(len(chunk) <= 3400 for chunk in chunks)
    assert any(
        "公告內容 2 /" in (embed.title or "")
        for payload in payloads
        for embed in payload.embeds
    )
    assert re.sub(r"\s+", "", "".join(chunks)) == re.sub(r"\s+", "", content)


def test_extremely_long_notice_splits_across_discord_messages() -> None:
    payloads = build_announcement_message_payloads(make_result(1, content="Notice body. " * 12000), owner_user_id=1)

    assert len(payloads) > 1
    assert all(len(payload.embeds) <= 10 for payload in payloads)
    assert all(
        sum(len(embed.title or "") + len(embed.description or "") + len(embed.footer.text or "") for embed in payload.embeds)
        <= 5800
        for payload in payloads
    )
    assert payloads[0].embeds[0].footer.text.startswith("內容 1 /")


def test_multiple_images_update_only_the_notice_first_embed() -> None:
    content = "First paragraph.\n\n" + ("Second paragraph. " * 1400)
    payload = build_announcement_message_payloads(
        make_result(1, content=content, images=("https://images.example/one.png", "https://images.example/two.png")),
        owner_user_id=1,
    )[0]
    view = payload.view
    assert isinstance(view, AnnouncementImageView)
    original_body = [embed.to_dict() for embed in payload.embeds[1:]]

    interaction = FakeInteraction()
    asyncio.run(view.next_image.callback(interaction))

    edited_embeds = interaction.response.edits[-1]["embeds"]
    assert edited_embeds[0].image.url == "https://images.example/two.png"
    assert [embed.to_dict() for embed in edited_embeds[1:]] == original_body
    assert "圖片 2 / 2" in edited_embeds[0].footer.text
    assert view.previous_image.disabled is False
    assert view.next_image.disabled is True
    assert {item.label for item in view.children} == {"◀ 上一張", "下一張 ▶"}


def test_no_or_single_image_has_no_image_navigation_view() -> None:
    no_image = build_announcement_message_payloads(make_result(1), owner_user_id=1)[0]
    one_image = build_announcement_message_payloads(
        make_result(2, images=("https://images.example/one.png",)), owner_user_id=1
    )[0]

    assert no_image.view is None
    assert no_image.embeds[0].image.url is None
    assert no_image.embeds[0].footer.text.endswith("圖片 0 / 0")
    assert one_image.view is None
    assert one_image.embeds[0].image.url == "https://images.example/one.png"
    assert one_image.embeds[0].footer.text.endswith("圖片 1 / 1")


def test_image_views_for_different_notices_are_independent() -> None:
    first = build_announcement_message_payloads(
        make_result(1, images=("https://images.example/1a.png", "https://images.example/1b.png")), owner_user_id=1
    )[0].view
    second = build_announcement_message_payloads(
        make_result(2, images=("https://images.example/2a.png", "https://images.example/2b.png")), owner_user_id=1
    )[0].view
    assert isinstance(first, AnnouncementImageView)
    assert isinstance(second, AnnouncementImageView)

    asyncio.run(first.next_image.callback(FakeInteraction()))
    assert first.image_index == 1
    assert second.image_index == 0


def test_owner_check_and_timeout_disable_image_controls() -> None:
    view = build_announcement_message_payloads(
        make_result(1, images=("https://images.example/one.png", "https://images.example/two.png")), owner_user_id=1
    )[0].view
    assert isinstance(view, AnnouncementImageView)
    other = FakeInteraction(user_id=2)

    assert asyncio.run(view.interaction_check(other)) is False
    assert other.response.messages[0][1] == {"ephemeral": True}
    message = FakeMessage()
    view.message = message
    asyncio.run(view.on_timeout())
    assert SEARCH_VIEW_TIMEOUT_SECONDS == 300
    assert all(item.disabled for item in view.children)
    assert message.edits[-1]["view"] is view


def test_raw_and_active_results_share_the_complete_renderer() -> None:
    raw_payload = build_announcement_message_payloads(
        make_result(1, source_kind="raw_post", source="joybomb_archive", region="tw", content="Legacy body."), owner_user_id=1
    )[0]
    active_payload = build_announcement_message_payloads(
        make_result(2, source="cn_official", region="cn", content="Active body."), owner_user_id=1
    )[0]

    assert "Legacy body." in raw_payload.embeds[0].description
    assert "Active body." in active_payload.embeds[0].description
    assert "台服" in raw_payload.embeds[0].description
    assert "陸服" in active_payload.embeds[0].description


def test_result_list_uses_safe_select_options_and_compact_public_embed() -> None:
    results = (
        make_result(1),
        make_result(2, region="cn", source="cn_official"),
    )
    embed = build_search_results_embed(results, keyword="願之庭")
    view = AnnouncementSearchResultView(
        results=results,
        owner_user_id=1,
        keyword="願之庭",
        source_filter="all",
    )
    select = view.children[0]

    assert "找到 2 筆公告" in embed.title
    assert "願之庭" in embed.description
    assert "First paragraph" not in embed.description
    assert "🇹🇼 台服（1）" in embed.description
    assert "🇨🇳 陸服（1）" in embed.description
    assert embed.footer.text == "依發布時間由新到舊・台服優先顯示"
    assert select.placeholder == "選擇公告"
    assert len(select.options) == 2
    assert [option.value for option in select.options] == ["0", "1"]
    assert all(len(option.label) <= 100 for option in select.options)
    assert all(len(option.description or "") <= 100 for option in select.options)


def test_result_list_with_ten_results_has_one_page_and_disabled_navigation() -> None:
    results = tuple(make_result(index) for index in range(1, 11))
    view = AnnouncementSearchResultView(
        results=results,
        owner_user_id=1,
        keyword="願之庭",
        source_filter="all",
    )

    assert view.total_pages == 1
    assert view.previous_page_button.disabled is True
    assert view.next_page_button.disabled is True
    assert [option.value for option in view.result_select.options] == [str(index) for index in range(10)]
    assert "第 1 / 1 頁" in view.embed().description


def test_result_list_with_eleven_results_updates_select_for_second_page() -> None:
    results = tuple(make_result(index) for index in range(1, 12))
    view = AnnouncementSearchResultView(
        results=results,
        owner_user_id=1,
        keyword="願之庭",
        source_filter="all",
    )
    interaction = FakeInteraction()

    assert view.total_pages == 2
    assert view.previous_page_button.disabled is True
    assert view.next_page_button.disabled is False
    asyncio.run(view.next_page_button.callback(interaction))

    assert view.page_index == 1
    assert "第 2 / 2 頁" in interaction.response.edits[-1]["embed"].description
    assert [option.value for option in view.result_select.options] == ["10"]
    assert view.previous_page_button.disabled is False
    assert view.next_page_button.disabled is True


def test_result_list_with_twenty_one_results_uses_global_numbers_and_page_boundaries() -> None:
    results = tuple(make_result(index) for index in range(1, 22))
    view = AnnouncementSearchResultView(
        results=results,
        owner_user_id=1,
        keyword="願之庭",
        source_filter="all",
    )
    interaction = FakeInteraction()

    assert view.total_pages == 3
    asyncio.run(view.next_page_button.callback(interaction))
    assert "11. **Notice 11**" in interaction.response.edits[-1]["embed"].description
    assert [option.value for option in view.result_select.options] == [str(index) for index in range(10, 20)]
    asyncio.run(view.next_page_button.callback(interaction))
    assert "21. **Notice 21**" in interaction.response.edits[-1]["embed"].description
    assert [option.value for option in view.result_select.options] == ["20"]
    assert view.next_page_button.disabled is True
    asyncio.run(view.previous_page_button.callback(interaction))
    assert view.page_index == 1
    assert view.previous_page_button.disabled is False


def test_result_select_uses_global_index_after_changing_page() -> None:
    results = tuple(make_result(index, content=f"第 {index} 篇完整公告。") for index in range(1, 12))
    view = AnnouncementSearchResultView(
        results=results,
        owner_user_id=1,
        keyword="海歌",
        source_filter="all",
    )
    asyncio.run(view.next_page_button.callback(FakeInteraction()))
    view.result_select._values = ["10"]
    interaction = FakeSelectionInteraction()

    asyncio.run(view.result_select.callback(interaction))

    assert "第 11 篇完整公告。" in interaction.followup.messages[0][1]["embeds"][0].description


def test_grouped_pages_show_full_region_totals_and_keep_select_order_in_sync() -> None:
    tw_results = tuple(
        make_result(
            index,
            source="tw_official",
            region="tw",
            content=f"台服第 {index} 篇。",
        )
        for index in range(1, 14)
    )
    cn_results = tuple(
        make_result(
            100 + index,
            source="cn_official",
            region="cn",
            content=f"陸服第 {index} 篇。",
        )
        for index in range(1, 10)
    )
    view = AnnouncementSearchResultView(
        results=(*tw_results, *cn_results),
        owner_user_id=1,
        keyword="活動",
        source_filter="all",
    )
    interaction = FakeInteraction()

    first_page = view.embed().description
    assert "🇹🇼 台服（13）" in first_page
    assert "🇨🇳 陸服" not in first_page
    assert "1. **Notice 1**" in first_page
    assert "10. **Notice 10**" in first_page
    assert [option.value for option in view.result_select.options] == [str(index) for index in range(10)]

    asyncio.run(view.next_page_button.callback(interaction))
    second_page = interaction.response.edits[-1]["embed"].description
    assert "🇹🇼 台服（13）" in second_page
    assert "🇨🇳 陸服（9）" in second_page
    assert "11. **Notice 11**" in second_page
    assert "14. **Notice 101**" in second_page
    assert [option.value for option in view.result_select.options] == [str(index) for index in range(10, 20)]
    assert view.result_select.options[0].label.startswith("11. Notice 11")
    assert view.result_select.options[3].label.startswith("14. Notice 101")
    assert view.result_select.options[3].description == "2026/07/23・陸服"

    asyncio.run(view.next_page_button.callback(interaction))
    third_page = interaction.response.edits[-1]["embed"].description
    assert "🇹🇼 台服" not in third_page
    assert "🇨🇳 陸服（9）" in third_page
    assert "21. **Notice 108**" in third_page
    assert "22. **Notice 109**" in third_page


def test_second_page_cross_region_selection_opens_its_matching_notice() -> None:
    tw_results = tuple(make_result(index, content=f"台服第 {index} 篇。") for index in range(1, 14))
    cn_results = tuple(
        make_result(100 + index, source="cn_official", region="cn", content=f"陸服第 {index} 篇。")
        for index in range(1, 10)
    )
    view = AnnouncementSearchResultView(
        results=(*tw_results, *cn_results),
        owner_user_id=1,
        keyword="活動",
        source_filter="all",
    )
    asyncio.run(view.next_page_button.callback(FakeInteraction()))
    view.result_select._values = ["13"]
    interaction = FakeSelectionInteraction()

    asyncio.run(view.result_select.callback(interaction))

    assert "陸服第 1 篇。" in interaction.followup.messages[0][1]["embeds"][0].description


def test_single_region_page_does_not_render_an_empty_other_region_section() -> None:
    tw_results = (make_result(1, source="tw_official", region="tw"), make_result(2, source="facebook", region="tw"))
    cn_results = (make_result(3, source="cn_official", region="cn"),)

    tw_embed = build_search_results_embed(tw_results, keyword="活動")
    cn_embed = build_search_results_embed(cn_results, keyword="活動")

    assert "🇹🇼 台服（2）" in tw_embed.description
    assert "🇨🇳 陸服" not in tw_embed.description
    assert "🇨🇳 陸服（1）" in cn_embed.description
    assert "🇹🇼 台服" not in cn_embed.description


def test_result_select_sends_selected_complete_notice_ephemerally() -> None:
    results = (
        make_result(1),
        make_result(2, content="第二篇完整公告。"),
    )
    view = AnnouncementSearchResultView(
        results=results,
        owner_user_id=1,
        keyword="海歌",
        source_filter="all",
    )
    select = view.children[0]
    select._values = ["1"]
    interaction = FakeSelectionInteraction()

    asyncio.run(select.callback(interaction))

    assert interaction.response.deferred is True
    assert len(interaction.followup.messages) == 1
    send_kwargs = interaction.followup.messages[0][1]
    assert send_kwargs["ephemeral"] is True
    assert "第二篇完整公告。" in send_kwargs["embeds"][0].description
    assert "view" not in send_kwargs


def test_result_select_uses_and_binds_image_view_only_for_multiple_images() -> None:
    results = (
        make_result(1),
        make_result(2, images=("https://images.example/one.png", "https://images.example/two.png")),
    )
    view = AnnouncementSearchResultView(
        results=results,
        owner_user_id=1,
        keyword="永夜",
        source_filter="all",
    )
    select = view.children[0]
    select._values = ["1"]
    interaction = FakeSelectionInteraction()

    asyncio.run(select.callback(interaction))

    send_kwargs = interaction.followup.messages[0][1]
    assert send_kwargs["ephemeral"] is True
    assert isinstance(send_kwargs["view"], AnnouncementImageView)
    assert send_kwargs["view"].message is interaction.followup.sent_messages[0]


def test_result_select_allows_repeated_choices_without_modifying_public_list() -> None:
    results = (make_result(1, content="第一篇。"), make_result(2, content="第二篇。"))
    view = AnnouncementSearchResultView(
        results=results,
        owner_user_id=1,
        keyword="願之庭",
        source_filter="all",
    )
    select = view.children[0]
    first_interaction = FakeSelectionInteraction()
    second_interaction = FakeSelectionInteraction()

    select._values = ["0"]
    asyncio.run(select.callback(first_interaction))
    select._values = ["1"]
    asyncio.run(select.callback(second_interaction))

    assert "第一篇。" in first_interaction.followup.messages[0][1]["embeds"][0].description
    assert "第二篇。" in second_interaction.followup.messages[0][1]["embeds"][0].description
    assert select.disabled is False


def test_result_select_logs_and_reports_payload_failure(monkeypatch, caplog) -> None:
    view = AnnouncementSearchResultView(
        results=(make_result(1), make_result(2)),
        owner_user_id=1,
        keyword="海歌",
        source_filter="all",
    )
    select = view.children[0]
    select._values = ["1"]
    interaction = FakeSelectionInteraction()

    def fail_payloads(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("payload failed")

    monkeypatch.setattr(search_view, "build_announcement_message_payloads", fail_payloads)
    asyncio.run(select.callback(interaction))

    assert "Announcement-search selection rendering failed" in caplog.text
    assert "RuntimeError: payload failed" in caplog.text
    assert interaction.followup.messages == [
        (("公告內容顯示失敗，請稍後再試。",), {"ephemeral": True})
    ]


def test_result_list_rejects_non_owner_and_disables_select_after_timeout() -> None:
    view = AnnouncementSearchResultView(
        results=(make_result(1), make_result(2)),
        owner_user_id=1,
        keyword="願之庭",
        source_filter="all",
    )
    other = FakeSelectionInteraction(user_id=2)

    assert asyncio.run(view.interaction_check(other)) is False
    assert other.response.messages == [
        ("這不是你的搜尋結果，請自行使用 /公告搜尋。", {"ephemeral": True})
    ]
    message = FakeMessage()
    view.message = message
    asyncio.run(view.on_timeout())
    assert all(item.disabled for item in view.children)
    assert message.edits[-1]["view"] is view
