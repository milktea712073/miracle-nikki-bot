"""v2 announcement state is independent from the legacy knowledge database."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import bot.main as bot_main
from announcement.models import Announcement, CN_OFFICIAL, TW_FACEBOOK_SOURCE, TW_OFFICIAL
from announcement.state_store import AnnouncementStateStore
from crawler.models import Post
from crawler.website_crawler import WebsiteAnnouncement, WebsiteCrawlResult


def announcement(external_id: str = "post-1") -> Announcement:
    return Announcement(
        source=TW_FACEBOOK_SOURCE,
        external_id=external_id,
        url=f"https://www.facebook.com/TwNikkiNikki/posts/{external_id}",
        title="官方公告",
        category=None,
        published_at=None,
        content_html=None,
        content_text="官方公告內容",
        images=("https://images.example.test/one.png",),
    )


def test_state_deduplicates_by_source_external_id_and_snapshots_delivery_targets(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    first_id = store.register(announcement(), [101, 102])
    second_id = store.register(announcement(), [999])

    assert first_id == second_id
    first = store.claim_deliveries(10)
    assert [item.channel_id for item in first] == [101, 102]
    assert all(item.announcement.external_id == "post-1" for item in first)


def test_state_deduplicates_by_canonical_url_when_external_id_changes(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    first = Announcement(
        source=TW_OFFICIAL, external_id="17322", url="https://official.example/news/17322?ref=home",
        title="公告標題", category="活動", published_at=None, content_html="<p>內容</p>",
        content_text="內容", images=(),
    )
    changed_identifier = Announcement(
        source=TW_OFFICIAL, external_id="alternate-17322", url="https://official.example/news/17322?ref=home",
        title="公告標題", category="活動", published_at=None, content_html="<p>內容</p>",
        content_text="內容", images=(),
    )

    assert store.register(first, [101]) == store.register(changed_identifier, [101])
    deliveries = store.claim_deliveries(10)
    assert len(deliveries) == 1
    assert deliveries[0].announcement.title == "公告標題"


def test_official_delivery_claim_does_not_pick_retained_facebook_records(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(announcement("legacy-facebook"), [101])
    official = Announcement(
        source=TW_OFFICIAL, external_id="17322", url="https://official.example/news/17322", title="官方",
        category="活動", published_at=None, content_html=None, content_text="內容", images=(),
    )
    store.register(official, [101])

    deliveries = store.claim_deliveries(10, sources=(TW_OFFICIAL, CN_OFFICIAL))

    assert [item.announcement.source for item in deliveries] == [TW_OFFICIAL]


def test_partial_channel_failure_retries_only_failed_delivery_and_marks_sent_after_success(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(announcement(), [101, 102])
    first, second = store.claim_deliveries(10)
    store.mark_delivery_sent(first.delivery_id, ["message-101"])
    store.mark_delivery_failed(second.delivery_id, "temporary Discord error")

    retry = store.claim_deliveries(10)
    assert [item.channel_id for item in retry] == [102]
    store.mark_delivery_sent(retry[0].delivery_id, ["message-102"])

    connection = sqlite3.connect(store.database_path)
    try:
        assert connection.execute("SELECT sent_at IS NOT NULL FROM announcements").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM announcement_deliveries WHERE status = 'sent'").fetchone()[0] == 2
    finally:
        connection.close()


def test_legacy_initialization_reads_sent_ledger_without_modifying_legacy_database(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(legacy_path)
    try:
        connection.execute("CREATE TABLE announcements (post_url TEXT)")
        connection.execute(
            "INSERT INTO announcements VALUES ('https://www.facebook.com/TwNikkiNikki/posts/legacy-post?ref=share')"
        )
        connection.commit()
    finally:
        connection.close()

    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    plan = store.legacy_initialization_plan(legacy_path)
    assert [item.external_id for item in plan.legacy_sent] == ["legacy-post"]
    assert store.initialize_legacy_sent(plan, [101]) == 1

    connection = sqlite3.connect(legacy_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 1
    finally:
        connection.close()
    assert store.claim_deliveries(10) == []


def test_legacy_initialization_does_not_treat_old_queue_status_as_delivery_evidence(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(legacy_path)
    try:
        connection.execute("CREATE TABLE announcement_jobs (post_url TEXT, status TEXT)")
        connection.execute(
            "INSERT INTO announcement_jobs VALUES ('https://www.facebook.com/TwNikkiNikki/posts/not-ledger', 'sent')"
        )
        connection.commit()
    finally:
        connection.close()

    plan = AnnouncementStateStore(tmp_path / "announcement_state.db").legacy_initialization_plan(legacy_path)
    assert plan.legacy_sent == ()


def test_tw_poller_writes_only_v2_state(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "announcement_state.db"
    store = AnnouncementStateStore(state_path)
    post = Post(
        post_id="v2-post",
        url="https://www.facebook.com/TwNikkiNikki/posts/v2-post",
        content="v2 公告",
        published_at=None,
        images=[],
    )
    monkeypatch.setattr(bot_main, "AnnouncementStateStore", lambda: store)
    monkeypatch.setattr(bot_main, "get_latest_posts", lambda _limit: [post])
    monkeypatch.setattr(bot_main, "TW_ANNOUNCEMENT_CHANNEL_IDS", [101])
    monkeypatch.setattr(bot_main, "tw_initial_poll_complete", asyncio.Event())

    asyncio.run(bot_main.poll_tw_announcements.coro())

    delivery = store.claim_deliveries(1)
    assert len(delivery) == 1
    assert delivery[0].announcement.external_id == "v2-post"


def test_official_poller_registers_each_source_once_without_legacy_database(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    tw = Announcement(
        source=TW_OFFICIAL, external_id="2", url="https://tw.example/news/2", title="TW",
        category="活動", published_at=None, content_html="<p>TW</p>", content_text="TW", images=(),
    )
    cn = Announcement(
        source=CN_OFFICIAL, external_id="2", url="https://cn.example/news/2", title="CN",
        category="公告", published_at=None, content_html="<p>CN</p>", content_text="CN", images=(),
    )
    monkeypatch.setattr(bot_main, "AnnouncementStateStore", lambda: store)
    monkeypatch.setattr(bot_main, "fetch_tw_official_announcements", lambda _limit: [tw])
    monkeypatch.setattr(bot_main, "fetch_cn_official_announcements", lambda _limit: [cn])
    monkeypatch.setattr(bot_main, "TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [101])
    monkeypatch.setattr(bot_main, "CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [202])
    monkeypatch.setattr(bot_main, "official_initial_poll_complete", asyncio.Event())
    store.set_official_baseline(TW_OFFICIAL, "1")
    store.set_official_baseline(CN_OFFICIAL, "1")

    asyncio.run(bot_main.poll_official_announcements.coro())
    asyncio.run(bot_main.poll_official_announcements.coro())

    deliveries = store.claim_deliveries(10)
    assert {(item.announcement.source, item.channel_id) for item in deliveries} == {
        (TW_OFFICIAL, 101),
        (CN_OFFICIAL, 202),
    }
    assert store.get_official_baseline(TW_OFFICIAL) == "2"
    assert store.get_official_baseline(CN_OFFICIAL) == "2"


def test_official_poller_without_baseline_does_not_enqueue_current_notices(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    announcement = Announcement(
        source=TW_OFFICIAL, external_id="2", url="https://tw.example/news/2", title="TW",
        category="活動", published_at=None, content_html=None, content_text="TW", images=(),
    )
    monkeypatch.setattr(bot_main, "AnnouncementStateStore", lambda: store)
    monkeypatch.setattr(bot_main, "fetch_tw_official_announcements", lambda _limit: [announcement])
    monkeypatch.setattr(bot_main, "fetch_cn_official_announcements", lambda _limit: [])
    monkeypatch.setattr(bot_main, "TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [101])
    monkeypatch.setattr(bot_main, "CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [])
    monkeypatch.setattr(bot_main, "official_initial_poll_complete", asyncio.Event())

    asyncio.run(bot_main.poll_official_announcements.coro())

    assert store.claim_deliveries(10) == []


def test_v2_worker_marks_each_channel_only_after_that_channel_succeeds(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    store.register(
        Announcement(
            source=TW_OFFICIAL, external_id="17322", url="https://official.example/news/17322",
            title="官方公告", category="活動", published_at=None, content_html=None,
            content_text="內容", images=(),
        ),
        [101, 102],
    )
    monkeypatch.setattr(bot_main, "AnnouncementStateStore", lambda: store)
    monkeypatch.setattr(bot_main, "TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [101, 102])
    monkeypatch.setattr(bot_main, "CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [])
    monkeypatch.setattr(bot_main, "official_initial_poll_complete", asyncio.Event())
    bot_main.official_initial_poll_complete.set()
    monkeypatch.setattr(bot_main, "v2_delivery_recovered", False)

    async def resolve(channel_id: int) -> int:
        return channel_id

    async def send(channel_id: int, _payload: dict[str, object]) -> list[int]:
        if channel_id == 102:
            raise RuntimeError("channel unavailable")
        return [1001]

    monkeypatch.setattr(bot_main, "resolve_announcement_channel", resolve)
    monkeypatch.setattr(bot_main, "send_post", send)
    asyncio.run(bot_main.process_v2_announcement_deliveries.coro())

    retry = store.claim_deliveries(10)
    assert [item.channel_id for item in retry] == [102]


def test_v2_disables_knowledge_commands_from_the_registered_tree() -> None:
    assert bot_main.bot.tree.get_command("活動") is None
    assert bot_main.bot.tree.get_command("套裝") is None
