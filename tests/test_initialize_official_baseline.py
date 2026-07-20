"""Tests for first-deployment official source baselines."""

from __future__ import annotations

from announcement.models import Announcement, CN_OFFICIAL, TW_OFFICIAL
from announcement.state_store import AnnouncementStateStore
from scripts.announcement import initialize_official_baseline


def notice(source: str, external_id: str) -> Announcement:
    return Announcement(
        source=source,
        external_id=external_id,
        url=f"https://official.example/{source}/{external_id}",
        title=f"{source} title",
        category=None,
        published_at=None,
        content_html=None,
        content_text="content",
        images=(),
    )


def test_dry_run_plan_does_not_create_announcements_or_deliveries(tmp_path) -> None:
    plan = initialize_official_baseline.build_plan(
        {TW_OFFICIAL: lambda _limit: [notice(TW_OFFICIAL, "17322")], CN_OFFICIAL: lambda _limit: [notice(CN_OFFICIAL, "988690")]}
    )

    assert [item.external_id for item in plan.announcements] == ["17322", "988690"]
    assert not (tmp_path / "announcement_state.db").exists()


def test_apply_baseline_persists_only_latest_ids(tmp_path) -> None:
    store = AnnouncementStateStore(tmp_path / "announcement_state.db")
    plan = initialize_official_baseline.OfficialBaselinePlan(
        (notice(TW_OFFICIAL, "17322"), notice(CN_OFFICIAL, "988690")), False
    )

    initialize_official_baseline.apply_plan(store, plan)

    assert store.get_official_baseline(TW_OFFICIAL) == "17322"
    assert store.get_official_baseline(CN_OFFICIAL) == "988690"
    assert store.claim_deliveries(10) == []
