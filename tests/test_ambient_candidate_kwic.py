from datetime import UTC, datetime

from scripts.analysis.chat_analysis.kwic import kwic_examples
from scripts.analysis.chat_analysis.models import ResearchMessage


def test_kwic_highlights_phrase_without_discord_ids() -> None:
    message = ResearchMessage("secret-message", "secret-user", datetime(2026, 1, 1, tzinfo=UTC), "我等很久終於復刻了")

    result = kwic_examples([message], "終於復刻", context_chars=20, maximum=10)

    assert result == [("2026-01", "我等很久**終於復刻**了")]
    assert "secret" not in str(result)
