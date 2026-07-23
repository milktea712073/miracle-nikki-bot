"""Tests for the complete per-notice announcement search renderer."""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

from announcement.search_models import AnnouncementSearchResult
from bot.announcement_search_view import (
    AnnouncementImageView,
    SEARCH_VIEW_TIMEOUT_SECONDS,
    build_announcement_message_payloads,
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
) -> AnnouncementSearchResult:
    return AnnouncementSearchResult(
        source_kind=source_kind,
        source_record_id=record_id,
        source=source,
        region=region,
        external_id=str(record_id),
        title=f"Notice {record_id}",
        canonical_url=f"https://official.example/{record_id}",
        published_at="2026-07-23T08:00:00+00:00",
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


def test_short_notice_is_complete_in_one_message_without_notice_pagination() -> None:
    payloads = build_announcement_message_payloads(make_result(1), owner_user_id=1)

    assert len(payloads) == 1
    assert len(payloads[0].embeds) == 1
    assert "First paragraph.\n\nSecond paragraph." in payloads[0].embeds[0].description
    assert payloads[0].view is None
    assert all("公告 X / N" not in (embed.footer.text or "") for embed in payloads[0].embeds)


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
