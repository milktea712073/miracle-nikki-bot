"""Ambient Nikki v1 is a low-frequency skill event, not a chat responder."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import bot.main as bot_main
from bot.ambient_nikki import AmbientNikkiService, AmbientNikkiSettings
from bot.ambient_nikki.service import TAIPEI_TIMEZONE, display_target
from bot.ambient_nikki.skills import (
    GENERAL_ROOM_EVENTS,
    GENERAL_TARGET_EVENTS,
    PREFIXES,
    SLEEP_ROOM_EVENTS,
    SLEEP_TARGET_EVENTS,
    render_general_event,
    render_sleep_event,
)

def settings(**overrides: object) -> AmbientNikkiSettings:
    values: dict[str, object] = {
        "enabled": True,
        "trigger_rate": 1.0,
        "sleep_trigger_rate": 1.0,
        "cooldown_minutes": 30,
        "channel_ids": frozenset({100}),
    }
    values.update(overrides)
    return AmbientNikkiSettings(**values)


def service(*random_values: float, **overrides: object) -> AmbientNikkiService:
    values = iter(random_values or (0.0,))
    return AmbientNikkiService(
        settings(**overrides),
        random_value=lambda: next(values, 0.0),
        choose_copy=lambda pool: pool[0],
    )


def at(hour: int) -> datetime:
    return datetime(2026, 7, 25, hour, tzinfo=TAIPEI_TIMEZONE)


def test_event_data_has_the_required_pool_sizes_and_core_target_copy() -> None:
    assert len(PREFIXES) >= 20
    assert len(GENERAL_TARGET_EVENTS) + len(GENERAL_ROOM_EVENTS) >= 40
    assert len(SLEEP_TARGET_EVENTS) + len(SLEEP_ROOM_EVENTS) >= 15
    assert "偷走了{target}的襪子" in GENERAL_TARGET_EVENTS
    assert "朝{target}扔了一顆鑽石" in GENERAL_TARGET_EVENTS
    assert "把一小袋金幣塞給了{target}" in GENERAL_TARGET_EVENTS
    assert "替{target}撿到了一枚星光幣" in GENERAL_TARGET_EVENTS
    assert "留下了一顆鑽石後就跑掉了" in GENERAL_ROOM_EVENTS
    assert "在地上撒了幾枚星光幣" in GENERAL_ROOM_EVENTS
    assert "替聊天室掛上了一顆小星星" in GENERAL_ROOM_EVENTS
    assert "把一隻小熊玩偶放在窗邊" in GENERAL_ROOM_EVENTS
    all_general_events = (*GENERAL_TARGET_EVENTS, *GENERAL_ROOM_EVENTS)
    currency_events = tuple(
        event for event in all_general_events if any(currency in event for currency in ("鑽石", "金幣", "星光幣"))
    )
    world_item_events = tuple(
        event
        for event in all_general_events
        if any(item in event for item in ("花", "蝴蝶", "羽毛", "鈕扣", "布料", "緞帶", "星星", "糖果", "茶點", "抱枕", "小熊", "大喵", "針線"))
    )
    assert len(currency_events) >= 20
    assert len(world_item_events) >= 30
    assert set(GENERAL_TARGET_EVENTS).isdisjoint(SLEEP_TARGET_EVENTS)
    assert set(GENERAL_ROOM_EVENTS).isdisjoint(SLEEP_ROOM_EVENTS)
    assert all(not line.endswith(("。", "！", "!", "…")) for line in (*GENERAL_TARGET_EVENTS, *GENERAL_ROOM_EVENTS, *SLEEP_TARGET_EVENTS, *SLEEP_ROOM_EVENTS))


def test_general_skill_can_trigger_from_any_message_content() -> None:
    event, reason = service(0.0).decide(guild_id=1, channel_id=100, target="搭配師", now=at(12))

    assert reason is None
    assert event is not None
    assert event.text.startswith(PREFIXES[0])
    assert event.text.endswith("偷走了搭配師的襪子")


def test_sleep_spell_only_uses_its_rate_between_0200_and_0559() -> None:
    event, reason = service(0.0).decide(guild_id=1, channel_id=100, target="玩家", now=at(2))
    daytime, daytime_reason = service(0.0).decide(guild_id=1, channel_id=100, target="玩家", now=at(6))

    assert reason is None and event is not None and event.text.endswith("替玩家蓋好了棉被")
    assert daytime_reason is None and daytime is not None
    assert daytime.text.endswith("偷走了玩家的襪子")


def test_night_can_still_trigger_general_skill_when_sleep_check_misses() -> None:
    event, reason = service(0.9, 0.0, sleep_trigger_rate=0.08).decide(
        guild_id=1, channel_id=100, target="玩家", now=at(5)
    )

    assert reason is None and event is not None
    assert event.text.endswith("偷走了玩家的襪子")


def test_no_skill_is_cast_when_both_independent_chances_miss() -> None:
    event, reason = service(0.9, 0.9, trigger_rate=0.03, sleep_trigger_rate=0.08).decide(
        guild_id=1, channel_id=100, target="玩家", now=at(3)
    )

    assert event is None and reason == "probability"


def test_guild_cooldown_records_only_after_success() -> None:
    ambient = service(0.0)
    now = at(12)
    event, _ = ambient.decide(guild_id=1, channel_id=100, target="玩家", now=now)

    assert event is not None
    ambient.record_success(1, now)
    blocked, reason = ambient.decide(guild_id=1, channel_id=100, target="玩家", now=now + timedelta(minutes=29))
    allowed, _ = ambient.decide(guild_id=2, channel_id=100, target="玩家", now=now + timedelta(minutes=1))

    assert blocked is None and reason == "cooldown"
    assert allowed is not None


def test_only_human_allowed_guild_messages_are_eligible() -> None:
    ambient = service(0.0)
    assert ambient.skip_reason(guild_id=None, channel_id=100, author_is_bot=False, is_webhook=False, is_system=False) == "direct_message"
    assert ambient.skip_reason(guild_id=1, channel_id=999, author_is_bot=False, is_webhook=False, is_system=False) == "channel_not_allowed"
    assert ambient.skip_reason(guild_id=1, channel_id=100, author_is_bot=True, is_webhook=False, is_system=False) == "author_bot"
    assert ambient.skip_reason(guild_id=1, channel_id=100, author_is_bot=False, is_webhook=True, is_system=False) == "webhook"
    assert ambient.skip_reason(guild_id=1, channel_id=100, author_is_bot=False, is_webhook=False, is_system=True) == "system_message"


def test_target_uses_display_name_then_name_without_a_mention() -> None:
    assert display_target(SimpleNamespace(display_name="芷妤", name="other")) == "芷妤"
    assert display_target(SimpleNamespace(display_name="", name="Nikki")) == "Nikki"
    assert display_target(SimpleNamespace()) == "玩家"


def test_rendered_events_are_short_npc_events_without_skill_or_rpg_terms() -> None:
    general = render_general_event("茶米茶", choose=lambda pool: pool[0])
    sleep = render_sleep_event("茶米茶", choose=lambda pool: pool[0])
    for text in (general, sleep):
        assert text.startswith(PREFIXES[0])
        assert len(text.split("\n")) == 2
        assert not any(term in text for term in ("【", "】", "使用了", "發動", "技能", "Buff", "Debuff"))
        prefix, event = text.split("\n")
        assert re.search(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]$", prefix)
        assert not re.search(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", event)
        assert not event.endswith(("。", "！", "!", "…"))
    assert "茶米茶" in general
    assert "{target}" not in general
    assert "{target}" not in GENERAL_ROOM_EVENTS[0]
    assert "{target}" not in SLEEP_ROOM_EVENTS[0]


def test_settings_default_disabled_and_invalid_values_use_safe_defaults(caplog) -> None:
    defaults = AmbientNikkiSettings.from_environment({})
    invalid = AmbientNikkiSettings.from_environment({
        "AMBIENT_NIKKI_ENABLED": "maybe", "AMBIENT_NIKKI_TRIGGER_RATE": "2",
        "AMBIENT_NIKKI_SLEEP_TRIGGER_RATE": "-1", "AMBIENT_NIKKI_COOLDOWN_MINUTES": "bad",
        "AMBIENT_NIKKI_CHANNEL_IDS": "bad,100",
    })

    assert defaults.enabled is False
    assert invalid == AmbientNikkiSettings(False, 0.03, 0.08, 30, frozenset({100}))
    assert "invalid" in caplog.text


def test_on_message_keeps_prefix_command_dispatch(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_ambient(_message) -> None:
        calls.append("ambient")

    async def fake_process_commands(_message) -> None:
        calls.append("commands")

    monkeypatch.setattr(bot_main, "handle_ambient_nikki_message", fake_ambient)
    monkeypatch.setattr(bot_main.bot, "process_commands", fake_process_commands)
    asyncio.run(bot_main.on_message(SimpleNamespace()))

    assert calls == ["ambient", "commands"]


def test_discord_handler_uses_no_mentions_and_records_after_reply(monkeypatch) -> None:
    ambient = service(0.0)
    message = _FakeMessage()
    monkeypatch.setattr(bot_main, "AMBIENT_NIKKI_SERVICE", ambient)

    asyncio.run(bot_main.handle_ambient_nikki_message(message))
    assert "偷走了測試玩家的襪子" in message.replies[0][0]
    assert "【" not in message.replies[0][0]
    assert message.replies[0][1] is False
    assert message.allowed_mentions is not None
    assert ambient.state.is_cooling_down(1, datetime.now(TAIPEI_TIMEZONE), 30)


class _FakeMessage:
    content = "任何聊天內容都不影響技能判定"
    author = SimpleNamespace(bot=False, display_name="測試玩家", name="fallback")
    guild = SimpleNamespace(id=1)
    channel = SimpleNamespace(id=100)
    webhook_id = None

    def __init__(self) -> None:
        self.replies: list[tuple[str, bool]] = []
        self.allowed_mentions = None

    def is_system(self) -> bool:
        return False

    async def reply(self, content: str, *, mention_author: bool, allowed_mentions) -> None:
        self.replies.append((content, mention_author))
        self.allowed_mentions = allowed_mentions
