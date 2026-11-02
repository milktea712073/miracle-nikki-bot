"""v2 announcement state is independent from the legacy knowledge database."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import bot.main as bot_main
from announcement.models import Announcement, CN_OFFICIAL, TW_FACEBOOK_SOURCE, TW_OFFICIAL
from announcement.state_store import AnnouncementStateStore
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


def official_announcement(
    source: str,
    external_id: str,
    *,
    published_at: datetime | None = None,
    url: str | None = None,
) -> Announcement:
    return Announcement(
        source=source,
        external_id=external_id,
        url=url or f"https://{source}.example/news/{external_id}",
        title=f"{source} {external_id}",
        category="notice",
        published_at=published_at,
        content_html=None,
        content_text=external_id,
        images=(),
    )


def configure_official_poller(
    monkeypatch,
    store: AnnouncementStateStore,
    *,
    tw_announcements: list[Announcement],
    cn_announcements: list[Announcement],
) -> None:
    monkeypatch.setattr(bot_main, "AnnouncementStateStore", lambda: store)
    monkeypatch.setattr(bot_main, "ENABLE_ANNOUNCEMENT_PIPELINE", True)
    monkeypatch.setattr(bot_main, "fetch_tw_official_announcements", lambda _limit: tw_announcements)
    monkeypatch.setattr(bot_main, "fetch_cn_official_announcements", lambda _limit: cn_announcements)
    monkeypatch.setattr(bot_main, "TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [101])
    monkeypatch.setattr(bot_main, "CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [202])
    monkeypatch.setattr(bot_main, "official_initial_poll_complete", asyncio.Event())


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


def test_main_does_not_expose_the_retired_facebook_live_poller() -> None:
    assert not hasattr(bot_main, "poll_tw_announcements")
    assert not hasattr(bot_main, "poll_facebook_posts")


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
    monkeypatch.setattr(bot_main, "ENABLE_ANNOUNCEMENT_PIPELINE", True)
    tw_baseline = official_announcement(TW_OFFICIAL, "1")
    cn_baseline = official_announcement(CN_OFFICIAL, "1")
    monkeypatch.setattr(bot_main, "fetch_tw_official_announcements", lambda _limit: [tw, tw_baseline])
    monkeypatch.setattr(bot_main, "fetch_cn_official_announcements", lambda _limit: [cn, cn_baseline])
    monkeypatch.setattr(bot_main, "TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [101])
    monkeypatch.setattr(bot_main, "CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [202])
    monkeypatch.setattr(bot_main, "official_initial_poll_complete", asyncio.Event())
    store.seed_official_seen_announcements((tw_baseline, cn_baseline))
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


def test_official_poller_finds_unseen_item_after_existing_anchor(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    newest = official_announcement(
        TW_OFFICIAL, "17333", published_at=datetime(2026, 8, 2, 4, 0, tzinfo=timezone.utc)
    )
    seen_anchor = official_announcement(
        TW_OFFICIAL, "17331", published_at=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
    )
    inserted_after_anchor = official_announcement(
        TW_OFFICIAL, "17332", published_at=datetime(2026, 8, 2, 3, 30, tzinfo=timezone.utc)
    )
    configure_official_poller(
        monkeypatch,
        store,
        tw_announcements=[newest, seen_anchor, inserted_after_anchor],
        cn_announcements=[],
    )
    store.seed_official_seen_announcements((seen_anchor,))
    store.set_official_baseline(TW_OFFICIAL, "17333")

    asyncio.run(bot_main.poll_official_announcements.coro())

    deliveries = store.claim_deliveries(10)
    assert [item.announcement.external_id for item in deliveries] == ["17332", "17333"]
    assert store.get_official_baseline(TW_OFFICIAL) == "17333"


def test_official_poller_uses_publish_time_not_external_id_order(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    newest = official_announcement(
        TW_OFFICIAL, "7", published_at=datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc)
    )
    older_new = official_announcement(
        TW_OFFICIAL, "999", published_at=datetime(2026, 8, 2, 7, 0, tzinfo=timezone.utc)
    )
    baseline = official_announcement(TW_OFFICIAL, "500")
    configure_official_poller(
        monkeypatch,
        store,
        tw_announcements=[newest, older_new, baseline],
        cn_announcements=[],
    )
    store.seed_official_seen_announcements((baseline,))
    store.set_official_baseline(TW_OFFICIAL, baseline.external_id)

    asyncio.run(bot_main.poll_official_announcements.coro())

    deliveries = store.claim_deliveries(10)
    assert [item.announcement.external_id for item in deliveries] == ["999", "7"]
    assert store.get_official_baseline(TW_OFFICIAL) == "7"


def test_official_poller_does_nothing_when_baseline_is_first(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    baseline = official_announcement(TW_OFFICIAL, "current")
    configure_official_poller(
        monkeypatch,
        store,
        tw_announcements=[baseline, official_announcement(TW_OFFICIAL, "older")],
        cn_announcements=[],
    )
    store.seed_official_seen_announcements((baseline, official_announcement(TW_OFFICIAL, "older")))
    store.set_official_baseline(TW_OFFICIAL, baseline.external_id)

    asyncio.run(bot_main.poll_official_announcements.coro())

    assert store.claim_deliveries(10) == []
    assert store.get_official_baseline(TW_OFFICIAL) == "current"


def test_official_poller_fails_closed_until_seen_window_is_initialized(monkeypatch, tmp_path: Path, caplog) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    configure_official_poller(
        monkeypatch,
        store,
        tw_announcements=[],
        cn_announcements=[
            official_announcement(CN_OFFICIAL, "newest"),
            official_announcement(CN_OFFICIAL, "older"),
        ],
    )
    store.set_official_baseline(CN_OFFICIAL, "missing-anchor")

    asyncio.run(bot_main.poll_official_announcements.coro())

    assert store.claim_deliveries(10) == []
    assert store.get_official_baseline(CN_OFFICIAL) == "missing-anchor"
    assert "CN official seen state is not initialized" in caplog.text


def test_official_poller_does_not_call_legacy_sources(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    baseline = official_announcement(TW_OFFICIAL, "current")
    configure_official_poller(
        monkeypatch,
        store,
        tw_announcements=[baseline],
        cn_announcements=[],
    )
    store.seed_official_seen_announcements((baseline,))
    store.set_official_baseline(TW_OFFICIAL, baseline.external_id)

    def legacy_fetch_must_not_run(_limit: int):
        raise AssertionError("legacy Facebook source must not participate in official polling")

    monkeypatch.setattr(bot_main, "get_latest_posts", legacy_fetch_must_not_run)

    asyncio.run(bot_main.poll_official_announcements.coro())


def test_official_poller_without_baseline_does_not_enqueue_current_notices(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    announcement = Announcement(
        source=TW_OFFICIAL, external_id="2", url="https://tw.example/news/2", title="TW",
        category="活動", published_at=None, content_html=None, content_text="TW", images=(),
    )
    monkeypatch.setattr(bot_main, "AnnouncementStateStore", lambda: store)
    monkeypatch.setattr(bot_main, "ENABLE_ANNOUNCEMENT_PIPELINE", True)
    monkeypatch.setattr(bot_main, "fetch_tw_official_announcements", lambda _limit: [announcement])
    monkeypatch.setattr(bot_main, "fetch_cn_official_announcements", lambda _limit: [])
    monkeypatch.setattr(bot_main, "TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [101])
    monkeypatch.setattr(bot_main, "CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS", [])
    monkeypatch.setattr(bot_main, "official_initial_poll_complete", asyncio.Event())

    asyncio.run(bot_main.poll_official_announcements.coro())

    assert store.claim_deliveries(10) == []


def test_official_seen_state_persists_and_isolated_by_source(tmp_path: Path) -> None:
    path = tmp_path / "announcement_state.db"
    tw = official_announcement(TW_OFFICIAL, "same-id")
    cn = official_announcement(CN_OFFICIAL, "same-id")
    store = AnnouncementStateStore(path)

    store.seed_official_seen_announcements((tw,))

    restarted = AnnouncementStateStore(path)
    assert restarted.is_official_announcement_seen(tw)
    assert not restarted.is_official_announcement_seen(cn)


def test_register_official_if_unseen_deduplicates_canonical_url_and_creates_one_delivery(tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    original = official_announcement(TW_OFFICIAL, "17332", url="https://official.example/news/17332")
    same_url = official_announcement(TW_OFFICIAL, "alternate-id", url="https://official.example/news/17332")

    assert store.register_official_if_unseen(original, [101])
    assert not store.register_official_if_unseen(same_url, [101])
    assert [item.announcement.external_id for item in store.claim_deliveries(10)] == ["17332"]


def test_failed_official_registration_does_not_mark_seen(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    item = official_announcement(TW_OFFICIAL, "17332")

    def fail_register(*_args, **_kwargs) -> int:
        raise RuntimeError("database write failed")

    monkeypatch.setattr(store, "_register_with_connection", fail_register)
    try:
        store.register_official_if_unseen(item, [101])
    except RuntimeError:
        pass
    else:
        raise AssertionError("registration failure must propagate")

    assert not store.is_official_announcement_seen(item)
    assert store.claim_deliveries(10) == []


def test_upgraded_state_with_only_legacy_anchor_does_not_bulk_queue(monkeypatch, tmp_path: Path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    current = official_announcement(TW_OFFICIAL, "17333")
    configure_official_poller(
        monkeypatch,
        store,
        tw_announcements=[current],
        cn_announcements=[],
    )
    store.set_official_baseline(TW_OFFICIAL, "17325")

    asyncio.run(bot_main.poll_official_announcements.coro())

    assert store.claim_deliveries(10) == []
    assert not store.has_official_seen_announcements(TW_OFFICIAL)


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
    monkeypatch.setattr(bot_main, "ENABLE_ANNOUNCEMENT_PIPELINE", True)
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
