"""Tests for explicit, channel-scoped official notice replay staging."""

from __future__ import annotations

import pytest

from announcement.models import Announcement, CN_OFFICIAL, TW_OFFICIAL
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


def historical_cn() -> Announcement:
    return Announcement(
        source=CN_OFFICIAL,
        external_id="988639",
        url="https://qjnn.qq.com/notice/988639.shtml",
        title="指定公告",
        category="公告",
        published_at=None,
        content_html="<p>內容</p>",
        content_text="指定內容",
        images=(),
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


def test_external_id_selects_a_non_latest_announcement_without_creating_state(tmp_path) -> None:
    state_path = tmp_path / "announcement_state.db"
    limits: list[int] = []

    def fetch(limit: int) -> list[Announcement]:
        limits.append(limit)
        return [latest(), historical_cn()]

    result = replay_latest_official.replay_latest(
        "cn",
        None,
        replay=False,
        state_database=state_path,
        external_id="988639",
        fetchers={"cn": fetch},
    )

    assert result.announcement == historical_cn()
    assert limits == [replay_latest_official.EXTERNAL_ID_LOOKUP_LIMIT]
    assert not state_path.exists()


def test_dry_run_output_ends_with_an_explicit_no_delivery_message(capsys, tmp_path) -> None:
    result = replay_latest_official.replay_latest(
        "cn",
        None,
        replay=False,
        state_database=tmp_path / "announcement_state.db",
        external_id="988639",
        fetchers={"cn": lambda _limit: [historical_cn()]},
    )

    replay_latest_official.print_result(result)

    assert capsys.readouterr().out.rstrip().endswith("Dry run only.")


def test_external_id_replay_reuses_the_existing_channel_scoped_delivery_reset(tmp_path) -> None:
    state_path = tmp_path / "announcement_state.db"
    result = replay_latest_official.replay_latest(
        "cn",
        303,
        replay=True,
        state_database=state_path,
        external_id="988639",
        fetchers={"cn": lambda _limit: [latest(), historical_cn()]},
    )

    assert result.announcement.external_id == "988639"
    pending = AnnouncementStateStore(state_path).claim_deliveries(10, sources=(CN_OFFICIAL,))
    assert [(item.announcement.external_id, item.channel_id) for item in pending] == [("988639", 303)]


def test_missing_external_id_prints_a_clear_error_without_creating_delivery(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(replay_latest_official, "FETCHERS", {"cn": lambda _limit: [historical_cn()]})
    state_path = tmp_path / "announcement_state.db"

    exit_code = replay_latest_official.main(
        [
            "--source", "cn",
            "--external-id", "not-found",
            "--state-database", str(state_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ERROR: Official announcement not found." in captured.err
    assert "Source: cn" in captured.err
    assert "External ID: not-found" in captured.err
    assert not state_path.exists()
