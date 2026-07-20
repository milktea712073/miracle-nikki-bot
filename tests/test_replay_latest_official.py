"""Tests for explicit, channel-scoped official notice replay staging."""

from __future__ import annotations

import pytest

from announcement.models import Announcement, TW_OFFICIAL
from announcement.state_store import AnnouncementStateStore
from scripts.announcement import replay_latest_official


def latest() -> Announcement:
    return Announcement(
        source=TW_OFFICIAL,
        external_id="17322",
        url="https://nu3.fearlessgames.net/news/17322",
        title="測試官方公告",
        category="活動",
        published_at=None,
        content_html="<p>內容</p>",
        content_text="內容",
        images=("https://images.example/one.png",),
    )


def test_dry_run_fetches_latest_without_creating_state_database(tmp_path) -> None:
    state_path = tmp_path / "announcement_state.db"
    result = replay_latest_official.replay_latest(
        "tw", None, replay=False, state_database=state_path, fetchers={"tw": lambda _limit: [latest()]}
    )

    assert result.replayed is False
    assert result.announcement.external_id == "17322"
    assert not state_path.exists()


def test_replay_resets_only_the_explicit_channel_delivery(tmp_path) -> None:
    state_path = tmp_path / "announcement_state.db"
    store = AnnouncementStateStore(state_path)
    store.register(latest(), [101, 202])
    first, second = store.claim_deliveries(10)
    store.mark_delivery_sent(first.delivery_id, ["one"])
    store.mark_delivery_sent(second.delivery_id, ["two"])

    result = replay_latest_official.replay_latest(
        "tw", 202, replay=True, state_database=state_path, fetchers={"tw": lambda _limit: [latest()]}
    )

    assert result.replayed is True
    retry = store.claim_deliveries(10, sources=(TW_OFFICIAL,))
    assert [item.channel_id for item in retry] == [202]


def test_replay_requires_an_explicit_channel() -> None:
    with pytest.raises(SystemExit) as error:
        replay_latest_official.parse_args(["--source", "tw", "--replay"])
    assert error.value.code == 2
