from datetime import UTC, datetime, timedelta

from scripts.analysis.chat_analysis.models import ResearchMessage
from scripts.analysis.chat_analysis.reply_pairs import find_replies, reply_quality_flags


def _message(identifier: str, author: str, seconds: int, content: str, **kwargs) -> ResearchMessage:
    return ResearchMessage(identifier, author, datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds), content, "channel", **kwargs)


def test_direct_reply_is_preferred_over_time_window_reply() -> None:
    trigger = _message("1", "a", 0, "這次全收")
    nearby = _message("2", "b", 10, "恭喜", reply_to_message_id="1")
    other = _message("3", "c", 20, "好看")

    replies = find_replies(trigger, [trigger, nearby, other], {"a": "player_1", "b": "player_2", "c": "player_3"}, window_seconds=300)

    assert [reply.text for reply in replies] == ["恭喜"]
    assert replies[0].direct_reply is True


def test_same_author_and_outside_window_are_not_replies() -> None:
    trigger = _message("1", "a", 0, "這次全收")
    own = _message("2", "a", 5, "真的好看")
    late = _message("3", "b", 301, "恭喜")

    assert find_replies(trigger, [trigger, own, late], {"a": "player_1", "b": "player_2"}, window_seconds=300) == []
    assert "too_generic" in reply_quality_flags("笑死")
