from datetime import UTC, datetime

from scripts.analysis.chat_analysis.models import ResearchMessage
from scripts.analysis.chat_analysis.ngrams import character_ngrams, mine_ngrams, repeated_short_phrases, suppress_overlapping_candidates


def test_character_ngrams_cover_two_to_six_chinese_characters() -> None:
    counts = character_ngrams("終於復刻了", 2, 6)

    assert counts["終於"] == 1
    assert counts["終於復刻"] == 1
    assert counts["終於復刻了"] == 1


def test_mined_ngram_retains_repeated_occurrences_in_one_message() -> None:
    message = ResearchMessage("1", "a", datetime(2026, 1, 1, tzinfo=UTC), "收嗎收嗎")

    assert len(mine_ngrams([message], 2, 2)["收嗎"]) == 2


def test_overlapping_candidates_prefer_longer_near_equally_frequent_phrase() -> None:
    from collections import Counter

    kept = suppress_overlapping_candidates(Counter({"終於復刻": 4, "復刻": 4, "終於": 4}))

    assert "終於復刻" in kept
    assert "復刻" not in kept


def test_repeated_short_phrase_normalizes_whitespace() -> None:
    message = ResearchMessage("1", "a", datetime(2026, 1, 1, tzinfo=UTC), "  想收   這套  ")

    assert list(repeated_short_phrases([message])) == ["想收 這套"]
