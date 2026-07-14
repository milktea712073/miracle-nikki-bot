import asyncio
from types import SimpleNamespace

import bot.main as bot_main
from bot.admin import checks
from bot.admin.knowledge_event_views import EventAdminView
from crawler.models import Post
from database.database import get_connection, init_database
from database.knowledge_query_repository import EventView, SuitView


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False
        self.messages: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def is_done(self) -> bool:
        return self.deferred

    async def defer(self, **_kwargs: object) -> None:
        self.deferred = True

    async def send_message(self, *args: object, **kwargs: object) -> None:
        self.messages.append((args, kwargs))


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def send(self, *args: object, **kwargs: object) -> None:
        self.messages.append((args, kwargs))


class FakeQueryInteraction:
    def __init__(self, channel_id: int) -> None:
        self.channel_id = channel_id
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.user = SimpleNamespace(id=1)


class FakeRepository:
    def get_event_by_name(self, _name: str) -> EventView:
        return EventView(1, "測試活動", None, None, None, [], [], None, None)

    def get_announcement_image_for_event(self, _name: str) -> None:
        return None

    def get_suit_by_name(self, _name: str) -> SuitView:
        return SuitView(2, "測試套裝", None, False, None, [])

    def get_display_image_for_suit(self, _suit_id: int) -> None:
        return None


def configure_channels(monkeypatch) -> None:
    monkeypatch.setattr(bot_main, "QUERY_CHANNEL_IDS", [101, 102])
    monkeypatch.setattr(bot_main, "ADMIN_CHANNEL_IDS", [201, 202])


def test_event_and_suit_queries_allow_multiple_query_and_admin_channels(monkeypatch) -> None:
    configure_channels(monkeypatch)
    monkeypatch.setattr(bot_main, "KnowledgeQueryRepository", lambda: FakeRepository())
    monkeypatch.setattr(bot_main, "is_administrator", lambda _interaction: False)
    monkeypatch.setattr(bot_main, "is_administrator_channel", lambda _channel_id: False)

    event_in_query_channel = FakeQueryInteraction(101)
    suit_in_query_channel = FakeQueryInteraction(102)
    event_in_admin_channel = FakeQueryInteraction(201)
    suit_in_admin_channel = FakeQueryInteraction(202)
    asyncio.run(bot_main.event_command.callback(event_in_query_channel, "測試活動"))
    asyncio.run(bot_main.suit_command.callback(suit_in_query_channel, "測試套裝"))
    asyncio.run(bot_main.event_command.callback(event_in_admin_channel, "測試活動"))
    asyncio.run(bot_main.suit_command.callback(suit_in_admin_channel, "測試套裝"))

    for interaction in (
        event_in_query_channel,
        suit_in_query_channel,
        event_in_admin_channel,
        suit_in_admin_channel,
    ):
        assert interaction.response.deferred is True
        assert len(interaction.followup.messages) == 1


def test_query_command_rejects_channels_outside_query_and_admin_lists(monkeypatch) -> None:
    configure_channels(monkeypatch)
    monkeypatch.setattr(bot_main, "ANNOUNCEMENT_CHANNEL_IDS", [301])
    announcement_event = FakeQueryInteraction(301)
    announcement_suit = FakeQueryInteraction(301)
    other_event = FakeQueryInteraction(999)
    other_suit = FakeQueryInteraction(999)

    asyncio.run(bot_main.event_command.callback(announcement_event, "測試活動"))
    asyncio.run(bot_main.suit_command.callback(announcement_suit, "測試套裝"))
    asyncio.run(bot_main.event_command.callback(other_event, "測試活動"))
    asyncio.run(bot_main.suit_command.callback(other_suit, "測試套裝"))

    for interaction in (announcement_event, announcement_suit, other_event, other_suit):
        assert interaction.response.deferred is False
        assert interaction.response.messages == [
            (("請到指定的查詢頻道使用此指令。",), {"ephemeral": True})
        ]


def test_query_cards_only_show_management_buttons_in_admin_channels(monkeypatch) -> None:
    configure_channels(monkeypatch)
    monkeypatch.setattr(bot_main, "KnowledgeQueryRepository", lambda: FakeRepository())
    monkeypatch.setattr(bot_main, "is_administrator", lambda _interaction: True)
    monkeypatch.setattr(
        bot_main, "is_administrator_channel", lambda channel_id: channel_id in {201, 202}
    )

    query_interaction = FakeQueryInteraction(101)
    admin_interaction = FakeQueryInteraction(201)
    asyncio.run(bot_main.event_command.callback(query_interaction, "測試活動"))
    asyncio.run(bot_main.suit_command.callback(admin_interaction, "測試套裝"))

    assert query_interaction.followup.messages[0][1].get("view") is None
    assert admin_interaction.followup.messages[0][1]["view"] is not None


def test_announcement_delivery_only_uses_configured_announcement_channels(monkeypatch) -> None:
    class Destination:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send(self, **kwargs: object) -> None:
            self.sent.append(kwargs)

    first, second = Destination(), Destination()
    destinations = {301: first, 302: second}
    monkeypatch.setattr(bot_main, "ANNOUNCEMENT_CHANNEL_IDS", [301, 302])
    monkeypatch.setattr(bot_main.bot, "get_channel", lambda channel_id: destinations.get(channel_id))

    asyncio.run(
        bot_main.send_announcement_post(
            {"publish_time": "2026/07/12 05:00", "content": "公告", "image_urls": []}
        )
    )

    assert len(first.sent) == 1
    assert len(second.sent) == 1


def test_new_permalink_without_published_at_is_saved_and_sent_once(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "announcements.db"
    init_database(database_path)
    post = Post(
        post_id="new-post",
        url="https://www.facebook.com/TwNikkiNikki/posts/new-post",
        content="官方公告",
        published_at=None,
        images=["https://images.example/official.png"],
    )
    saved_posts: list[Post] = []
    sent_posts: list[dict[str, object]] = []

    class FakeRawRepository:
        def save_raw_post(self, value: Post) -> None:
            saved_posts.append(value)

    async def record_send(value: dict[str, object]) -> None:
        sent_posts.append(value)

    monkeypatch.setattr(bot_main, "get_latest_posts", lambda _limit: [post])
    monkeypatch.setattr(bot_main, "RawPostRepository", lambda: FakeRawRepository())
    monkeypatch.setattr(bot_main, "get_connection", lambda: get_connection(database_path))
    monkeypatch.setattr(bot_main, "send_announcement_post", record_send)

    asyncio.run(bot_main.check_new_post.coro())
    asyncio.run(bot_main.check_new_post.coro())

    assert saved_posts == [post, post]
    assert len(sent_posts) == 1
    assert sent_posts[0]["publish_time"] is None
    connection = get_connection(database_path)
    try:
        row = connection.execute("SELECT publish_time, post_url FROM announcements").fetchone()
    finally:
        connection.close()
    assert row == ("", post.url)


def test_management_callback_rejects_wrong_channel_even_for_configured_admin(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_ADMIN_USER_IDS", "1")
    monkeypatch.setenv("ADMIN_CHANNEL_IDS", "201,202")
    response = FakeResponse()
    interaction = SimpleNamespace(
        channel_id=999,
        user=SimpleNamespace(id=1),
        response=response,
        followup=FakeFollowup(),
    )
    view = EventAdminView(1, "測試活動")
    edit_button = next(child for child in view.children if child.label == "✏️ 編輯")

    asyncio.run(edit_button.callback(interaction))

    assert response.messages == [
        (("請到指定的管理頻道進行編輯。",), {"ephemeral": True})
    ]
    assert checks.is_administrator_channel(201) is True
    assert checks.is_administrator_channel(202) is True
