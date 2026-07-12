import asyncio
from pathlib import Path

import pytest

from bot.admin.knowledge_image_views import ImagePreviewView, create_image_preview_embed
from bot.admin.knowledge_suit_views import (
    ReturnSuitCardView,
    SuitRelationSelectView,
    SuitAdminView,
    SuitEditSettingsView,
    SuitImageEventSelectView,
    create_edit_embed,
    refresh_edit_card,
)
from bot.main import (
    create_event_embed,
    create_suit_embed,
    create_suit_response_view,
    format_activity_records,
)
from bot.knowledge_formatting import format_cost_line
from database.database import get_connection, init_database
from database.knowledge_query_repository import KnowledgeQueryRepository


def seed_suit(
    database_path: Path,
    *,
    event_type: str = "普通活動",
    acquisition_method: str = "花鑽",
    single_cost: str | None = None,
    event_total_cost: str | None = None,
    periods: list[tuple[str, str | None]] | None = None,
    suit_count: int = 1,
    image_url: str | None = None,
) -> None:
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        connection.execute("INSERT INTO event_types (name) VALUES (?)", (event_type,))
        event_type_id = connection.execute("SELECT id FROM event_types").fetchone()[0]
        connection.execute(
            "INSERT INTO acquisition_methods (name) VALUES (?)", (acquisition_method,)
        )
        acquisition_method_id = connection.execute(
            "SELECT id FROM acquisition_methods"
        ).fetchone()[0]
        event_id = connection.execute(
            """INSERT INTO events (name, event_type_id, created_at, updated_at)
               VALUES ('風林火山', ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')""",
            (event_type_id,),
        ).lastrowid
        for period_type, start_at in periods or [("debut", "2026-06-30T05:00:00+08:00")]:
            connection.execute(
                """INSERT INTO event_periods (event_id, period_type, start_at, end_at, created_at)
                   VALUES (?, ?, ?, '2026-07-07T23:59:00+08:00', '2026-01-01T00:00:00+00:00')""",
                (event_id, period_type, start_at),
            )
        for position in range(suit_count):
            suit_name = "山" if position == 0 else f"副套{position}"
            suit_id = connection.execute(
                """INSERT INTO suits (name, created_at, updated_at)
                   VALUES (?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')""",
                (suit_name,),
            ).lastrowid
            connection.execute(
                """INSERT INTO event_suits
                   (event_id, suit_id, acquisition_method_id, display_order)
                   VALUES (?, ?, ?, ?)""",
                (event_id, suit_id, acquisition_method_id, position),
            )
            if position == 0 and single_cost is not None:
                connection.execute(
                    """INSERT INTO cost_records (event_id, suit_id, cost_scope, cost_text)
                       VALUES (?, ?, 'single_suit', ?)""",
                    (event_id, suit_id, single_cost),
                )
        if event_total_cost is not None:
            connection.execute(
                """INSERT INTO cost_records (event_id, suit_id, cost_scope, cost_text)
                   VALUES (?, NULL, 'event_total', ?)""",
                (event_id, event_total_cost),
            )
        if image_url:
            raw_post_id = connection.execute(
                """INSERT INTO raw_posts
                   (source, source_post_id, url, content, scraped_at, updated_at)
                   VALUES ('facebook', 'raw-1', 'https://example.test/raw-1', '風林火山公告',
                   '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"""
            ).lastrowid
            connection.execute(
                "INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at) VALUES (?, ?, 0, '2026-01-01T00:00:00+00:00')",
                (raw_post_id, image_url),
            )
        connection.commit()
    finally:
        connection.close()


def get_suit_card(database_path: Path):
    repository = KnowledgeQueryRepository(database_path)
    suit = repository.get_suit_by_name("山")
    assert suit is not None
    return suit, create_suit_embed(suit)


def field_values(embed) -> dict[str, str]:
    return {field.name: field.value for field in embed.fields}


@pytest.mark.parametrize(
    ("period_type", "label"),
    [("debut", "首次"), ("rerun", "復刻"), ("wish_gate", "心願之門")],
)
def test_period_type_labels(period_type, label):
    period = type("Period", (), {"period_type": period_type, "start_at": "2026-06-30T05:00:00+08:00"})()

    assert format_activity_records([period]) == [f"{label}　2026/06/30"]


def test_single_suit_event_uses_event_total_cost_as_fallback(tmp_path):
    database_path = tmp_path / "single-fallback.db"
    seed_suit(database_path, event_total_cost="1992")

    suit, embed = get_suit_card(database_path)

    assert suit.events[0].cost_text == "1992"
    assert "💎 花費：1992 鑽" in embed.description
    assert "💎 花鑽" not in field_values(embed)


def test_multi_suit_event_does_not_use_event_total_as_single_suit_cost(tmp_path):
    database_path = tmp_path / "multi-no-fallback.db"
    seed_suit(database_path, event_total_cost="18000", suit_count=2)

    suit, embed = get_suit_card(database_path)

    assert suit.events[0].cost_text is None
    assert "💎 花費：花鑽" in embed.description


@pytest.mark.parametrize(
    ("method", "cost", "expected"),
    [
        ("花鑽", "1992", "💎 花費：1992 鑽"),
        ("花鑽", "約1992鑽", "💎 花費：約1992 鑽"),
        ("儲值", "648", "💎 花費：648 星曜石"),
        ("體力", "1800", "💎 花費：1800 體力"),
    ],
)
def test_resource_cost_display(tmp_path, method, cost, expected):
    database_path = tmp_path / f"{method}.db"
    seed_suit(database_path, acquisition_method=method, single_cost=cost)

    _, embed = get_suit_card(database_path)

    assert expected in embed.description


def test_free_suit_does_not_show_unorganized_cost(tmp_path):
    database_path = tmp_path / "free.db"
    seed_suit(database_path, acquisition_method="免費")

    _, embed = get_suit_card(database_path)

    assert "💎 花費：免費" in embed.description
    assert "尚未整理" not in embed.description


def test_single_suit_activity_uses_related_announcement_image_as_fallback(tmp_path):
    database_path = tmp_path / "image.db"
    seed_suit(database_path, image_url="https://example.test/announcement.jpg")
    repository = KnowledgeQueryRepository(database_path)
    suit = repository.get_suit_by_name("山")
    assert suit is not None

    image_url = repository.get_display_image_for_suit(suit.id)
    embed = create_suit_embed(suit, image_url)

    assert embed.image.url == "https://example.test/announcement.jpg"


def test_suit_card_without_image_is_valid(tmp_path):
    database_path = tmp_path / "no-image.db"
    seed_suit(database_path)
    suit, embed = get_suit_card(database_path)

    assert KnowledgeQueryRepository(database_path).get_announcement_image_for_events(
        [event.event_name for event in suit.events]
    ) is None
    assert embed.image.url is None


def test_multi_suit_event_does_not_fallback_to_activity_image(tmp_path):
    database_path = tmp_path / "multi-image.db"
    seed_suit(
        database_path,
        suit_count=2,
        image_url="https://example.test/activity-image.jpg",
    )
    repository = KnowledgeQueryRepository(database_path)
    suit = repository.get_suit_by_name("山")
    assert suit is not None

    assert repository.get_display_image_for_suit(suit.id) is None


def test_assigned_primary_suit_image_is_displayed(tmp_path):
    database_path = tmp_path / "assigned-image.db"
    expected_url = "https://example.test/suit-image.jpg"
    seed_suit(database_path, suit_count=2, image_url=expected_url)
    repository = KnowledgeQueryRepository(database_path)
    suit = repository.get_suit_by_name("山")
    assert suit is not None
    event = repository.get_event_by_name("風林火山")
    assert event is not None
    raw_image = repository.get_raw_images_for_event(event.id)[0]

    repository.assign_primary_image_to_suit(suit.id, raw_image.id)

    assert repository.get_primary_image_for_suit(suit.id) == expected_url
    assert repository.get_display_image_for_suit(suit.id) == expected_url


def test_assigned_image_is_not_reused_for_another_suit(tmp_path):
    database_path = tmp_path / "separate-images.db"
    seed_suit(
        database_path,
        suit_count=2,
        image_url="https://example.test/first-suit-image.jpg",
    )
    repository = KnowledgeQueryRepository(database_path)
    first_suit = repository.get_suit_by_name("山")
    second_suit = repository.get_suit_by_name("副套1")
    event = repository.get_event_by_name("風林火山")
    assert first_suit is not None and second_suit is not None and event is not None
    raw_image = repository.get_raw_images_for_event(event.id)[0]

    repository.assign_primary_image_to_suit(first_suit.id, raw_image.id)

    assert repository.get_display_image_for_suit(first_suit.id) == raw_image.image_url
    assert repository.get_display_image_for_suit(second_suit.id) is None


def test_event_card_uses_date_only_activity_records(tmp_path):
    database_path = tmp_path / "event-card.db"
    seed_suit(
        database_path,
        event_type="大閣",
        periods=[
            ("debut", "2018-08-01T05:00:00+08:00"),
            ("rerun", "2024-07-01T05:00:00+08:00"),
        ],
    )
    event = KnowledgeQueryRepository(database_path).get_event_by_name("風林火山")
    assert event is not None

    embed = create_event_embed(event)

    assert "活動期間：2024/07/01～2026/07/07" in embed.description


def test_administrator_suit_response_has_management_buttons():
    view = create_suit_response_view(42, is_admin=True)

    assert isinstance(view, SuitAdminView)
    assert view.suit_id == 42
    assert {item.label for item in view.children} == {"✏️ 編輯套裝", "🖼️ 編輯圖片", "✅ 標記已確認"}


def test_multi_event_relation_selector_contains_only_the_relation_choice(tmp_path):
    database_path = tmp_path / "direct-relation-select.db"
    seed_suit(database_path)
    context = KnowledgeQueryRepository(database_path).get_suit_edit_context(1)
    assert context is not None

    view = SuitRelationSelectView(context, owner_user_id=1, public_message=None)

    assert len(view.children) == 1
    assert view.children[0].placeholder == "選擇活動關聯"
    assert {item.label for item in ReturnSuitCardView(1).children} == {"↩️ 返回套裝卡"}


def test_regular_player_suit_response_has_no_management_buttons():
    assert create_suit_response_view(42, is_admin=False) is None


def test_edit_suit_updates_single_cost_and_card_immediately(tmp_path):
    database_path = tmp_path / "edit-cost.db"
    seed_suit(database_path, single_cost="1000")
    repository = KnowledgeQueryRepository(database_path)
    context = repository.get_suit_edit_context(1)
    assert context is not None
    event = context.events[0]

    repository.update_suit_card_data(
        context.suit_id,
        event.id,
        event.acquisition_method_id,
        "1992",
        False,
    )

    updated_suit = repository.get_suit_by_name("山")
    assert updated_suit is not None
    assert updated_suit.events[0].cost_text == "1992"
    assert "💎 花費：1992 鑽" in create_suit_embed(updated_suit).description


def test_mansion_suit_can_enable_live2d(tmp_path):
    database_path = tmp_path / "mansion-live2d.db"
    seed_suit(database_path, event_type="大閣")
    repository = KnowledgeQueryRepository(database_path)
    context = repository.get_suit_edit_context(1)
    assert context is not None
    event = context.events[0]

    repository.update_suit_card_data(
        context.suit_id, event.id, event.acquisition_method_id, None, True
    )

    suit = repository.get_suit_by_name("山")
    assert suit is not None
    assert suit.is_live2d is True
    assert "✨ Live2D" in create_suit_embed(suit).description


def test_non_mansion_suit_cannot_enable_live2d(tmp_path):
    database_path = tmp_path / "regular-live2d.db"
    seed_suit(database_path, event_type="普通活動")
    repository = KnowledgeQueryRepository(database_path)
    context = repository.get_suit_edit_context(1)
    assert context is not None
    event = context.events[0]

    with pytest.raises(ValueError, match="大閣或故事套裝"):
        repository.update_suit_card_data(
            context.suit_id, event.id, event.acquisition_method_id, None, True
        )

    suit = repository.get_suit_by_name("山")
    assert suit is not None
    assert suit.is_live2d is False


def test_image_preview_starts_with_the_first_actual_image(tmp_path):
    database_path = tmp_path / "suit-image-picker.db"
    seed_suit(database_path, image_url="https://example.test/suit.jpg")
    repository = KnowledgeQueryRepository(database_path)
    suit = repository.get_suit_by_name("山")
    event = repository.get_event_by_name("風林火山")
    assert suit is not None and event is not None
    images = repository.get_raw_images_for_event(event.id)

    view = ImagePreviewView(suit.id, suit.name, event.name, images, owner_user_id=1)

    assert view.suit_id == suit.id
    assert view.embed().image.url == "https://example.test/suit.jpg"
    assert "圖片：1 / 1" in view.embed().description


def test_image_preview_next_and_previous_select_the_expected_image(tmp_path):
    database_path = tmp_path / "preview-navigation.db"
    seed_suit(database_path, image_url="https://example.test/first.jpg")
    connection = get_connection(database_path)
    try:
        raw_post_id = connection.execute("SELECT id FROM raw_posts").fetchone()[0]
        connection.execute(
            "INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at) VALUES (?, ?, 1, '2026-01-01T00:00:00+00:00')",
            (raw_post_id, "https://example.test/second.jpg"),
        )
        connection.commit()
    finally:
        connection.close()
    repository = KnowledgeQueryRepository(database_path)
    suit = repository.get_suit_by_name("山")
    event = repository.get_event_by_name("風林火山")
    assert suit is not None and event is not None
    images = repository.get_raw_images_for_event(event.id)
    view = ImagePreviewView(suit.id, suit.name, event.name, images, owner_user_id=1)

    view.index = 1
    view.previous.disabled = False
    view.next.disabled = True
    assert view.embed().image.url == "https://example.test/second.jpg"
    view.index = 0
    assert view.embed().image.url == "https://example.test/first.jpg"


def test_image_preview_marks_an_invalid_url_without_raising():
    image = type("RawImage", (), {"id": 1, "image_url": "not-a-valid-url"})()

    embed = create_image_preview_embed("元氣應援", "奇迹演唱會", [image], 0)

    assert embed.image.url is None
    assert any(field.value == "此圖片目前無法預覽。" for field in embed.fields)


def test_multi_activity_image_flow_starts_with_an_event_selector(tmp_path):
    database_path = tmp_path / "multi-event-selector.db"
    seed_suit(database_path, image_url="https://example.test/source.jpg")
    repository = KnowledgeQueryRepository(database_path)
    context = repository.get_suit_edit_context(1)
    assert context is not None

    view = SuitImageEventSelectView(1, context.suit_name, context.events * 2, owner_user_id=1)

    assert len(view.children) == 1
    assert view.children[0].placeholder == "選擇圖片來源活動"


def test_suit_edit_card_uses_one_resource_summary_line(tmp_path):
    database_path = tmp_path / "edit-resource-summary.db"
    seed_suit(database_path, single_cost="1992")
    context = KnowledgeQueryRepository(database_path).get_suit_edit_context(1)
    assert context is not None

    embed = create_edit_embed(context, context.events[0])

    assert "💎 花鑽：1992鑽" in embed.description
    assert not any(field.name in {"單套花費", "取得方式"} for field in embed.fields)


def test_non_mansion_edit_view_has_only_cost_and_acquisition_buttons(tmp_path):
    database_path = tmp_path / "regular-edit-controls.db"
    seed_suit(database_path, event_type="普通活動")
    context = KnowledgeQueryRepository(database_path).get_suit_edit_context(1)
    assert context is not None

    view = SuitEditSettingsView(context, context.events[0])

    assert "✏️ 校正套裝資訊" in {item.label for item in view.children}


def test_mansion_edit_view_also_has_a_dedicated_live2d_button(tmp_path):
    database_path = tmp_path / "mansion-edit-controls.db"
    seed_suit(database_path, event_type="大閣")
    context = KnowledgeQueryRepository(database_path).get_suit_edit_context(1)
    assert context is not None

    view = SuitEditSettingsView(context, context.events[0])

    labels = {item.label for item in view.children}
    assert "✏️ 校正套裝資訊" in labels
    assert "✨ 設定 Live2D" in labels


def test_edit_view_has_return_button_with_the_current_suit_context(tmp_path):
    database_path = tmp_path / "return-suit-card.db"
    seed_suit(database_path)
    context = KnowledgeQueryRepository(database_path).get_suit_edit_context(1)
    assert context is not None

    view = SuitEditSettingsView(context, context.events[0])
    return_button = next(item for item in view.children if item.label == "⬅️ 返回套裝卡")

    assert view.context.suit_id == 1
    assert return_button.label == "⬅️ 返回套裝卡"


@pytest.mark.parametrize(
    ("method", "cost", "expected"),
    [
        ("花鑽", "1992", "💎 花鑽：1992鑽"),
        ("花鑽", "1992鑽", "💎 花鑽：1992鑽"),
        ("體力", "1800", "⚡ 體力：1800體力"),
        ("儲值", "648", "⭐ 星曜石：648星曜石"),
        ("免費", None, "🎁 免費"),
    ],
)
def test_format_cost_line_uses_one_line_and_does_not_duplicate_units(method, cost, expected):
    assert format_cost_line(method, cost) == expected


def test_saved_edit_embed_has_footer_and_latest_cost(tmp_path):
    database_path = tmp_path / "saved-edit-embed.db"
    seed_suit(database_path, single_cost="1992")
    context = KnowledgeQueryRepository(database_path).get_suit_edit_context(1)
    assert context is not None

    embed = create_edit_embed(context, context.events[0], saved=True)

    assert "💎 花鑽：1992鑽" in embed.description
    assert embed.footer.text == "✅ 已儲存"


def test_saved_edit_refreshes_the_same_message_with_latest_values(tmp_path, monkeypatch):
    database_path = tmp_path / "refresh-edit-card.db"
    seed_suit(database_path, single_cost="1000")
    repository = KnowledgeQueryRepository(database_path)
    context = repository.get_suit_edit_context(1)
    assert context is not None
    event = context.events[0]
    repository.update_suit_card_data(
        context.suit_id, event.id, event.acquisition_method_id, "1992", False
    )

    class FakeMessage:
        def __init__(self):
            self.edited = None

        async def edit(self, **kwargs):
            self.edited = kwargs

    from bot.admin import knowledge_suit_views

    monkeypatch.setattr(
        knowledge_suit_views,
        "KnowledgeQueryRepository",
        lambda: KnowledgeQueryRepository(database_path),
    )
    message = FakeMessage()

    asyncio.run(refresh_edit_card(message, context.suit_id, event.id))

    assert "💎 花鑽：1992鑽" in message.edited["embed"].description
    assert message.edited["embed"].footer.text == "✅ 已儲存"
    assert message.edited["view"].message is message
