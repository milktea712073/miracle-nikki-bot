from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from knowledge import story_event_reference as reference
from scripts.diagnostic import story_event_match_diagnostic as diagnostic


def write_reference(tmp_path: Path, events: list[dict[str, object]]) -> Path:
    path = tmp_path / "story_events.json"
    path.write_text(json.dumps({"schema_version": 1, "events": events}, ensure_ascii=False), encoding="utf-8")
    return path


def event_payload(name: str = "夏沫海歌") -> dict[str, object]:
    return {
        "canonical_name": name,
        "aliases": ["夏末海歌"] if name == "夏沫海歌" else [],
        "category": "故事套裝",
        "periods": [
            {"type": "debut", "date": "2017-10", "date_precision": "month"},
            {"type": "wish_gate", "date": "2023-06", "date_precision": "month"},
        ],
    }


def test_canonical_name_match() -> None:
    matches = reference.match_story_events("【復刻】夏沫海歌即將限時開放")

    assert [(match.canonical_name, match.matched_text, match.match_type, match.confidence) for match in matches] == [
        ("夏沫海歌", "夏沫海歌", "canonical", 1.0)
    ]


def test_alias_normalizes_to_canonical_name() -> None:
    matches = reference.match_story_events("夏末海歌將於心願之門開放")

    assert len(matches) == 1
    assert matches[0].canonical_name == "夏沫海歌"
    assert matches[0].matched_text == "夏末海歌"
    assert matches[0].match_type == "alias"
    assert matches[0].confidence == 0.98


def test_general_activity_is_not_fuzzy_matched() -> None:
    assert reference.match_story_events("【活動】仲夏登入送，完成任務可領取獎勵。") == []


def test_month_and_day_dates_are_validated() -> None:
    events = reference.load_story_event_reference()
    wind_forest = reference.find_story_event("風林火山", events)
    summer_song = reference.find_story_event("夏沫海歌", events)

    assert wind_forest is not None
    assert wind_forest.periods[-1].date == "2024-07-01"
    assert wind_forest.periods[-1].date_precision == "day"
    assert summer_song is not None
    assert summer_song.periods[0].date == "2017-10"
    assert summer_song.periods[0].date_precision == "month"


def test_wish_gate_is_not_converted_to_rerun() -> None:
    summer_song = reference.find_story_event("夏沫海歌")

    assert summer_song is not None
    assert [(period.type, period.date) for period in summer_song.periods][-1] == ("wish_gate", "2023-06")


def test_multiple_story_events_return_multiple_candidates() -> None:
    matches = reference.match_story_events("夏沫海歌與永夜國之夢將於本期回歸")

    assert [match.canonical_name for match in matches] == ["夏沫海歌", "永夜國之夢"]


@pytest.mark.parametrize(
    "events, expected_error",
    [
        ([{"aliases": [], "category": "故事套裝", "periods": []}], "canonical_name"),
        ([event_payload(), event_payload()], "duplicate canonical_name"),
        ([{**event_payload(), "periods": [{"type": "debut", "date": "2017-10-01", "date_precision": "month"}]}], "does not match month"),
        ([{**event_payload(), "periods": [{"type": "wish_gate", "date": "2023-06", "date_precision": "month"}]}], None),
    ],
)
def test_reference_validation(tmp_path: Path, events: list[dict[str, object]], expected_error: str | None) -> None:
    path = write_reference(tmp_path, events)

    if expected_error is not None:
        with pytest.raises(reference.StoryEventReferenceError, match=expected_error):
            reference.load_story_event_reference(path)
    else:
        loaded = reference.load_story_event_reference(path)
        assert loaded[0].periods[0].type == "wish_gate"


def test_loading_reference_has_no_mutable_global_state() -> None:
    first = reference.load_story_event_reference()
    second = reference.load_story_event_reference()

    assert first == second
    assert first is not second
    assert first[0] is not second[0]


def test_diagnostic_text_mode_reports_multiple_matches_without_database_access(capsys: pytest.CaptureFixture[str]) -> None:
    assert diagnostic.main(["--text", "夏沫海歌與永夜國之夢"]) == 0

    output = capsys.readouterr().out
    assert "matched story events: 2" in output
    assert "needs_review: true" in output
    assert "夏沫海歌" in output
    assert "永夜國之夢" in output


def test_read_raw_posts_uses_a_read_only_connection(tmp_path: Path) -> None:
    database_path = tmp_path / "raw.db"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE raw_posts (id INTEGER PRIMARY KEY, source TEXT, url TEXT, content TEXT)")
    connection.execute(
        "INSERT INTO raw_posts (id, source, url, content) VALUES (1, 'facebook', 'https://example.test/post', '夏沫海歌')"
    )
    connection.commit()
    connection.close()

    records = diagnostic.read_raw_posts(
        database_path=database_path,
        raw_post_id=1,
        limit=1,
        source="facebook",
    )

    assert records[0]["raw_post_id"] == 1
    assert records[0]["title"] == "夏沫海歌"
