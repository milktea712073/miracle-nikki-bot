"""Tests for the stdlib-only local Ambient Nikki chat research report."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.research.analyze_discord_chat import (
    ChatMessage,
    chinese_ngrams,
    emoji_statistics,
    filter_game_messages,
    game_filter_reason,
    keyword_cooccurrence,
    keyword_in_context,
    keyword_statistics,
    load_keyword_groups,
    load_keywords,
    load_messages,
    load_event_markers,
    load_stopwords,
    main,
    monthly_keyword_counts,
    keyword_lifetime,
    render_report,
)


def write_export(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "message_id": "1", "author_id": "a", "author_name": "Alice",
                    "timestamp": "2026-01-01T00:00:00Z", "content": "收嗎 我想收2D 🤣",
                    "is_bot": False, "attachment_count": 0,
                },
                {
                    "message_id": "2", "author_id": "b", "author_name": "Bob",
                    "timestamp": "2026-01-02T00:00:00Z", "content": "648好貴，但福袋好看 😭",
                    "is_bot": False, "attachment_count": 0,
                },
                {
                    "message_id": "3", "author_id": "a", "author_name": "Alice",
                    "timestamp": "2026-01-03T00:00:00Z", "content": "收嗎",
                    "is_bot": False, "attachment_count": 0,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_keyword_statistics_counts_occurrences_and_message_coverage(tmp_path: Path) -> None:
    source = tmp_path / "chat.json"
    write_export(source)
    stats = keyword_statistics(load_messages(source), ("收", "648", "福袋"))

    assert stats["收"].occurrences == 3
    assert stats["收"].message_count == 2
    assert stats["648"].occurrences == 1


def test_game_mode_filters_only_analysis_messages() -> None:
    messages = [
        _message("1", "收嗎"),
        _message("2", "https://example.test/announcement"),
        _message("3", "```python\nprint('x')\n```"),
        _message("4", "> quoted announcement"),
        _message("5", '{"announcement": "data"}'),
        _message("6", "<div>HTML</div>"),
        _message("7", "Traceback (most recent call last): ValueError: bad"),
        _message("8", "收" * 151),
    ]

    kept, excluded = filter_game_messages(messages)

    assert [message.message_id for message in kept] == ["1"]
    assert excluded == 7
    assert game_filter_reason("想收這套") is None
    assert game_filter_reason("ValueError: bad input") == "stack_trace"


def test_keyword_in_context_limits_each_side_and_keeps_occurrence_order() -> None:
    messages = [_message("1", "前言想收這套，第二次不要收大閣，最後收完了")]

    contexts = keyword_in_context(messages, "收")

    assert len(contexts) == 3
    assert "想收這套" in contexts[0]
    assert "不要收大閣" in contexts[1]
    assert "收完了" in contexts[2]


def test_keyword_in_context_caps_examples_at_fifty() -> None:
    messages = [_message(str(index), "收嗎") for index in range(1, 61)]

    assert len(keyword_in_context(messages, "收")) == 50


def test_keyword_cooccurrence_uses_messages_not_nlp() -> None:
    messages = [_message("1", "收大閣"), _message("2", "收2D"), _message("3", "課648")]

    counts = keyword_cooccurrence(messages, ("收", "大閣", "2D", "課", "648"))

    assert counts["收"] == {"大閣": 1, "2D": 1}
    assert counts["課"] == {"648": 1}


def test_emoji_statistics_counts_overall_and_per_player() -> None:
    overall, by_author = emoji_statistics([_message("1", "收嗎🤣🤣", author="a"), _message("2", "好貴😭", author="b")])

    assert overall == {"🤣": 2, "😭": 1}
    assert by_author["a"] == {"🤣": 2}
    assert by_author["b"] == {"😭": 1}


def test_stopwords_are_removed_before_chinese_ngrams(tmp_path: Path) -> None:
    stopword_file = tmp_path / "stopwords.txt"
    stopword_file.write_text("哈哈\n", encoding="utf-8")
    messages = [_message("1", "哈哈收嗎")]

    grams = chinese_ngrams(messages, 2, load_stopwords(stopword_file))

    assert "哈哈" not in grams
    assert grams["收嗎"] == 1


def test_keyword_config_keeps_categories_and_flattens_unique_terms(tmp_path: Path) -> None:
    config = tmp_path / "keywords.json"
    config.write_text('{"收套": ["收", "收嗎"], "活動": ["收", "大閣"]}', encoding="utf-8")

    assert load_keyword_groups(config) == {"收套": ("收", "收嗎"), "活動": ("大閣",)}
    assert load_keywords(config) == ("收", "收嗎", "大閣")


def test_report_is_anonymized_and_contains_ambient_research_sections(tmp_path: Path) -> None:
    source = tmp_path / "chat.json"
    write_export(source)
    messages = load_messages(source)
    groups = {"收套": ("收", "收嗎"), "課金": ("648",)}

    report = render_report(messages, groups, compare=True)

    assert "### 收套" in report and "共 5 次" in report
    assert "## 3. Keyword In Context" in report
    assert "## 4. 關鍵字共現" in report
    assert "## 5. Emoji 統計" in report
    assert "## 10. 玩家比較" in report
    assert "## 11. Ambient Trigger 排名" in report
    assert "## 13. 下一步建議" in report
    assert "★★★★☆" in report
    assert "玩家 1" in report and "玩家 2" in report
    assert "Alice" not in report and "Bob" not in report


def test_analysis_cli_game_mode_writes_filtered_markdown_report(tmp_path: Path) -> None:
    source = tmp_path / "chat.json"
    output = tmp_path / "reports" / "report.md"
    write_export(source)

    assert main([str(source), "--output", str(output), "--mode", "game", "--compare"]) == 0
    report = output.read_text(encoding="utf-8")
    assert "- 分析模式：game" in report
    assert "# 玩家聊天語言研究報告" in report


def test_monthly_counts_lifetime_stability_and_burst() -> None:
    messages = [
        _dated_message("1", "2026-01-10T00:00:00Z", "收"),
        _dated_message("2", "2026-02-10T00:00:00Z", "收收收"),
        _dated_message("3", "2026-03-10T00:00:00Z", "大閣"),
    ]

    monthly, message_counts = monthly_keyword_counts(messages, ("收", "大閣"))
    lifetime = keyword_lifetime(monthly, "收")

    assert message_counts == {"2026-01": 1, "2026-02": 1, "2026-03": 1}
    assert monthly["2026-02"]["收"] == 3
    assert lifetime is not None
    assert lifetime.first_seen == "2026-01"
    assert lifetime.last_seen == "2026-02"
    assert lifetime.active_months == 2
    assert lifetime.total_months == 3
    assert lifetime.stability_stars == 4
    assert lifetime.peak_count == 3
    assert lifetime.peak_month == "2026-02"
    assert lifetime.burst_stars == 2


def test_temporal_report_contains_timeline_event_marker_and_compare_by_month(tmp_path: Path) -> None:
    source = tmp_path / "chat.json"
    events = tmp_path / "events.json"
    write_export(source)
    events.write_text('[{"date": "2026-01", "label": "新大閣"}]', encoding="utf-8")
    groups = {"收套": ("收",), "活動": ("大閣",), "課金": ("648",)}

    report = render_report(
        load_messages(source), groups, compare=True, event_markers=load_event_markers(events)
    )

    assert "## 14. 時間分析" in report
    assert "### Trigger Timeline" in report
    assert "2026-01 █" in report
    assert "Active Months：" in report
    assert "### Monthly Top Trigger" in report
    assert "Event：新大閣" in report
    assert "### Compare by Month" in report
    assert "## 建議長期 Trigger" in report
    assert "## 建議活動 Trigger" in report
    assert "## 玩家語言演變" in report


def _message(message_id: str, content: str, author: str = "a") -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        author_id=author,
        author_name=author,
        timestamp=load_messages_timestamp(message_id),
        content=content,
    )


def _dated_message(message_id: str, timestamp: str, content: str) -> ChatMessage:
    from datetime import datetime

    return ChatMessage(message_id, "a", "A", datetime.fromisoformat(timestamp.replace("Z", "+00:00")), content)


def load_messages_timestamp(message_id: str):
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=int(message_id))
