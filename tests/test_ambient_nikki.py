"""Ambient Xiao Nuan replies are opt-in and safe to test without Discord."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import bot.main as bot_main
from bot.interactions.ambient_nikki import (
    TAIPEI_TIMEZONE,
    AmbientNikkiEngine,
    AmbientNikkiSettings,
    find_ambient_nikki_match,
    load_ambient_nikki_lines,
    normalize_message_text,
)


LINES_PATH = Path(__file__).resolve().parents[1] / "bot" / "interactions" / "nikki_lines.json"
LINES = load_ambient_nikki_lines(LINES_PATH)
assert LINES is not None


def test_line_file_contains_only_dialogue_without_speaker_prefix() -> None:
    for category in LINES.categories.values():
        assert all("小暖：" not in line for line in category.responses)
        for _requires, responses in category.conditional_responses:
            assert all("小暖：" not in line for line in responses)


def settings(**overrides: object) -> AmbientNikkiSettings:
    values: dict[str, object] = {
        "enabled": True,
        "response_chance": 1.0,
        "cooldown_seconds": 0,
        "daily_limit": 5,
        "channel_ids": frozenset({100}),
    }
    values.update(overrides)
    return AmbientNikkiSettings(**values)


def engine(**settings_overrides: object) -> AmbientNikkiEngine:
    return AmbientNikkiEngine(
        settings(**settings_overrides),
        LINES,
        random_value=lambda: 0.0,
        choose_line=lambda pool: pool[0],
    )


def now(hour: int = 12) -> datetime:
    return datetime(2026, 7, 25, hour, tzinfo=TAIPEI_TIMEZONE)


def decide(ambient: AmbientNikkiEngine, content: str, when: datetime | None = None):
    return ambient.decide(content=content, guild_id=1, channel_id=100, now=when or now())


def test_normalize_message_text_trims_collapses_spaces_and_lowercases_ascii() -> None:
    assert normalize_message_text("  HELLO   會收嗎  ") == "hello 會收嗎"


def test_collect_question_phrase_matches() -> None:
    match = find_ambient_nikki_match("這次會收嗎", LINES)

    assert match is not None
    assert match.category == "collect_question"


def test_collected_phrase_wins_over_shorter_overlapping_phrase() -> None:
    match = find_ambient_nikki_match("我收完了", LINES)

    assert match is not None
    assert match.category == "collected"
    assert match.trigger == "收完了"


def test_ordinary_phrase_with_single_collect_character_does_not_match() -> None:
    assert find_ambient_nikki_match("今天收工了", LINES) is None


def test_recharge_phrase_matches() -> None:
    response = decide(engine(), "這次課多少？")

    assert response is not None
    assert response.category == "recharge"


def test_648_uses_its_exclusive_response_pool() -> None:
    response = decide(engine(), "這次要不要課 648")

    assert response is not None
    assert response.line == "648……是很慎重的決定呢。"


def test_generic_recharge_phrase_does_not_use_648_line() -> None:
    response = decide(engine(), "這次課嗎")

    assert response is not None
    assert response.line != "648……是很慎重的決定呢。"


def test_bot_and_non_whitelisted_channel_messages_are_not_considered() -> None:
    ambient = engine()

    assert not ambient.can_consider(
        content="會收嗎", guild_id=1, channel_id=100, author_is_bot=True, is_webhook=False, is_system=False
    )
    assert not ambient.can_consider(
        content="會收嗎", guild_id=1, channel_id=999, author_is_bot=False, is_webhook=False, is_system=False
    )
    assert not ambient.can_consider(
        content="會收嗎", guild_id=None, channel_id=100, author_is_bot=False, is_webhook=False, is_system=False
    )


def test_probability_miss_does_not_reply() -> None:
    ambient = AmbientNikkiEngine(
        settings(response_chance=0.12), LINES, random_value=lambda: 0.12, choose_line=lambda pool: pool[0]
    )

    assert decide(ambient, "會收嗎") is None


def test_decision_reports_non_sensitive_skip_reasons() -> None:
    ambient = engine(cooldown_seconds=600, daily_limit=1)
    first = now()
    ambient.record_success(guild_id=1, now=first)

    _response, reason = ambient.decide_with_reason(
        content="會收嗎", guild_id=1, channel_id=100, now=first + timedelta(seconds=1)
    )
    assert reason == "cooldown"

    disabled = engine(enabled=False)
    _response, reason = disabled.decide_with_reason(
        content="會收嗎", guild_id=1, channel_id=100, now=first
    )
    assert reason == "disabled"


def test_global_cooldown_blocks_second_response() -> None:
    ambient = engine(cooldown_seconds=600)
    first = now()
    assert decide(ambient, "會收嗎", first) is not None
    ambient.record_success(guild_id=1, now=first)

    assert decide(ambient, "復刻了", first + timedelta(seconds=599)) is None


def test_daily_limit_resets_using_taipei_date() -> None:
    ambient = engine(daily_limit=1)
    first = datetime(2026, 7, 25, 23, 59, tzinfo=TAIPEI_TIMEZONE)
    assert decide(ambient, "會收嗎", first) is not None
    ambient.record_success(guild_id=1, now=first)

    assert decide(ambient, "復刻了", first + timedelta(seconds=1)) is None
    assert decide(ambient, "復刻了", first + timedelta(minutes=2)) is not None


def test_feature_defaults_to_disabled_and_invalid_settings_use_safe_defaults(caplog) -> None:
    defaults = AmbientNikkiSettings.from_environment({})
    invalid = AmbientNikkiSettings.from_environment(
        {
            "ENABLE_AMBIENT_NIKKI": "maybe",
            "AMBIENT_NIKKI_RESPONSE_CHANCE": "2",
            "AMBIENT_NIKKI_COOLDOWN_SECONDS": "-1",
            "AMBIENT_NIKKI_DAILY_LIMIT": "not-a-number",
            "AMBIENT_NIKKI_CHANNEL_IDS": "bad,100",
        }
    )

    assert not defaults.enabled
    assert invalid == AmbientNikkiSettings(False, 0.12, 600, 5, frozenset({100}))
    assert "invalid" in caplog.text


def test_missing_or_invalid_line_file_disables_only_ambient_feature(tmp_path: Path, caplog) -> None:
    assert load_ambient_nikki_lines(tmp_path / "missing.json") is None
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")

    assert load_ambient_nikki_lines(invalid) is None
    assert "Ambient Nikki is disabled" in caplog.text


def test_on_message_keeps_prefix_command_dispatch_when_ambient_handler_returns(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_ambient(_message) -> None:
        calls.append("ambient")

    async def fake_process_commands(_message) -> None:
        calls.append("commands")

    monkeypatch.setattr(bot_main, "handle_ambient_nikki_message", fake_ambient)
    monkeypatch.setattr(bot_main.bot, "process_commands", fake_process_commands)

    asyncio.run(bot_main.on_message(SimpleNamespace()))

    assert calls == ["ambient", "commands"]


def test_discord_handler_records_only_after_a_successful_reply(monkeypatch) -> None:
    ambient = engine()
    message = _FakeMessage()
    monkeypatch.setattr(bot_main, "AMBIENT_NIKKI_ENGINE", ambient)

    asyncio.run(bot_main.handle_ambient_nikki_message(message))

    assert message.replies == [("🌸 這次的套裝也很漂亮呢，搭配師會收下嗎？", False)]
    assert ambient.daily_counts[(1, datetime.now(TAIPEI_TIMEZONE).date())] == 1


class _FakeMessage:
    content = "會收嗎"
    author = SimpleNamespace(bot=False)
    guild = SimpleNamespace(id=1)
    channel = SimpleNamespace(id=100)
    webhook_id = None

    def __init__(self) -> None:
        self.replies: list[tuple[str, bool]] = []

    def is_system(self) -> bool:
        return False

    async def reply(self, content: str, *, mention_author: bool) -> None:
        self.replies.append((content, mention_author))
