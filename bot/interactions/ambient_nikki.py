"""Pure, opt-in ambient Xiao Nuan reply logic.

This module deliberately has no discord.py dependency so its matching, limits,
and configuration behaviour can be tested without a connected bot.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


LOGGER = logging.getLogger(__name__)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
DEFAULT_RESPONSE_CHANCE = 0.12
DEFAULT_COOLDOWN_SECONDS = 600
DEFAULT_DAILY_LIMIT = 5


@dataclass(frozen=True)
class AmbientNikkiSettings:
    enabled: bool
    response_chance: float
    cooldown_seconds: int
    daily_limit: int
    channel_ids: frozenset[int]

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        logger: logging.Logger = LOGGER,
    ) -> "AmbientNikkiSettings":
        environment = os.environ if environment is None else environment
        return cls(
            enabled=_load_boolean(environment, "ENABLE_AMBIENT_NIKKI", False, logger),
            response_chance=_load_probability(environment, logger),
            cooldown_seconds=_load_nonnegative_integer(
                environment,
                "AMBIENT_NIKKI_COOLDOWN_SECONDS",
                DEFAULT_COOLDOWN_SECONDS,
                logger,
            ),
            daily_limit=_load_nonnegative_integer(
                environment,
                "AMBIENT_NIKKI_DAILY_LIMIT",
                DEFAULT_DAILY_LIMIT,
                logger,
            ),
            channel_ids=_load_channel_ids(environment, logger),
        )


@dataclass(frozen=True)
class AmbientNikkiCategory:
    triggers: tuple[str, ...]
    responses: tuple[str, ...]
    conditional_responses: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class AmbientNikkiLines:
    categories: dict[str, AmbientNikkiCategory]


@dataclass(frozen=True)
class AmbientNikkiMatch:
    category: str
    trigger: str


@dataclass(frozen=True)
class AmbientNikkiResponse:
    category: str
    line: str


def normalize_message_text(text: str) -> str:
    """Normalize only whitespace and ASCII letter casing before phrase matching."""
    return re.sub(r"\s+", " ", text.strip()).lower()


def load_ambient_nikki_lines(path: Path, *, logger: logging.Logger = LOGGER) -> AmbientNikkiLines | None:
    """Load validated lines, disabling the feature instead of failing bot startup."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _parse_lines(payload)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        logger.error("Ambient Nikki is disabled because its line file is invalid: %s", error)
        return None


def find_ambient_nikki_match(text: str, lines: AmbientNikkiLines) -> AmbientNikkiMatch | None:
    """Choose the longest explicit configured phrase, preserving JSON order for ties."""
    normalized = normalize_message_text(text)
    if not normalized:
        return None

    candidates: list[tuple[int, int, int, AmbientNikkiMatch]] = []
    for category_index, (category_name, category) in enumerate(lines.categories.items()):
        for trigger_index, trigger in enumerate(category.triggers):
            if trigger in normalized:
                candidates.append(
                    (-len(trigger), category_index, trigger_index, AmbientNikkiMatch(category_name, trigger))
                )
    if not candidates:
        return None
    return min(candidates)[3]


class AmbientNikkiEngine:
    """In-memory decision and successful-response accounting for ambient replies."""

    def __init__(
        self,
        settings: AmbientNikkiSettings,
        lines: AmbientNikkiLines,
        *,
        random_value: Callable[[], float] = random.random,
        choose_line: Callable[[tuple[str, ...]], str] = random.choice,
    ) -> None:
        self.settings = settings
        self.lines = lines
        self.random_value = random_value
        self.choose_line = choose_line
        self.last_response_at: datetime | None = None
        self.daily_counts: dict[tuple[int, date], int] = {}

    def can_consider(
        self,
        *,
        content: str | None,
        guild_id: int | None,
        channel_id: int | None,
        author_is_bot: bool,
        is_webhook: bool,
        is_system: bool,
    ) -> bool:
        return self.eligibility_skip_reason(
            content=content,
            guild_id=guild_id,
            channel_id=channel_id,
            author_is_bot=author_is_bot,
            is_webhook=is_webhook,
            is_system=is_system,
        ) is None

    def eligibility_skip_reason(
        self,
        *,
        content: str | None,
        guild_id: int | None,
        channel_id: int | None,
        author_is_bot: bool,
        is_webhook: bool,
        is_system: bool,
    ) -> str | None:
        """Return a non-sensitive reason when a message cannot be considered."""
        if not self.settings.enabled:
            return "disabled"
        if not self.settings.channel_ids or channel_id not in self.settings.channel_ids:
            return "channel_not_allowed"
        if guild_id is None:
            return "direct_message"
        if author_is_bot:
            return "author_bot"
        if is_webhook:
            return "webhook"
        if is_system:
            return "system_message"
        if not content or not normalize_message_text(content):
            return "empty_content"
        return None

    def decide_with_reason(
        self,
        *,
        content: str,
        guild_id: int,
        channel_id: int,
        now: datetime,
    ) -> tuple[AmbientNikkiResponse | None, str | None]:
        """Return a response or a concise reason without changing state."""
        eligibility_reason = self.eligibility_skip_reason(
            content=content,
            guild_id=guild_id,
            channel_id=channel_id,
            author_is_bot=False,
            is_webhook=False,
            is_system=False,
        )
        if eligibility_reason is not None:
            return None, eligibility_reason
        now = _as_taipei_time(now)
        if self._is_cooling_down(now):
            return None, "cooldown"
        if self._has_reached_daily_limit(guild_id, now.date()):
            return None, "daily_limit"
        match = find_ambient_nikki_match(content, self.lines)
        if match is None:
            return None, "no_keyword_match"
        if self.random_value() >= self.settings.response_chance:
            return None, "probability"
        category = self.lines.categories[match.category]
        response_pool = _response_pool(category, normalize_message_text(content))
        if not response_pool:
            return None, "empty_response_pool"
        return AmbientNikkiResponse(match.category, self.choose_line(response_pool)), None

    def decide(
        self,
        *,
        content: str,
        guild_id: int,
        channel_id: int,
        now: datetime,
    ) -> AmbientNikkiResponse | None:
        """Return one possible response without mutating cooldown or daily state."""
        response, _reason = self.decide_with_reason(
            content=content,
            guild_id=guild_id,
            channel_id=channel_id,
            now=now,
        )
        return response

    def record_success(self, *, guild_id: int, now: datetime) -> None:
        """Record only after Discord has accepted the ordinary text reply."""
        now = _as_taipei_time(now)
        day = now.date()
        self.last_response_at = now
        self.daily_counts[(guild_id, day)] = self.daily_counts.get((guild_id, day), 0) + 1

    def _is_cooling_down(self, now: datetime) -> bool:
        return bool(
            self.last_response_at is not None
            and now - self.last_response_at < timedelta(seconds=self.settings.cooldown_seconds)
        )

    def _has_reached_daily_limit(self, guild_id: int, day: date) -> bool:
        return self.daily_counts.get((guild_id, day), 0) >= self.settings.daily_limit



def _load_boolean(
    environment: Mapping[str, str], name: str, default: bool, logger: logging.Logger
) -> bool:
    value = environment.get(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    logger.warning("%s is invalid; using safe default %s.", name, default)
    return default


def _load_probability(environment: Mapping[str, str], logger: logging.Logger) -> float:
    value = environment.get("AMBIENT_NIKKI_RESPONSE_CHANCE", "").strip()
    if not value:
        return DEFAULT_RESPONSE_CHANCE
    try:
        probability = float(value)
    except ValueError:
        probability = -1.0
    if 0 <= probability <= 1:
        return probability
    logger.warning("AMBIENT_NIKKI_RESPONSE_CHANCE is invalid; using safe default %s.", DEFAULT_RESPONSE_CHANCE)
    return DEFAULT_RESPONSE_CHANCE


def _load_nonnegative_integer(
    environment: Mapping[str, str], name: str, default: int, logger: logging.Logger
) -> int:
    value = environment.get(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        parsed = -1
    if parsed >= 0:
        return parsed
    logger.warning("%s is invalid; using safe default %s.", name, default)
    return default


def _load_channel_ids(environment: Mapping[str, str], logger: logging.Logger) -> frozenset[int]:
    channel_ids: set[int] = set()
    for raw_value in environment.get("AMBIENT_NIKKI_CHANNEL_IDS", "").split(","):
        value = raw_value.strip()
        if not value:
            continue
        if value.isdigit():
            channel_ids.add(int(value))
        else:
            logger.warning("Ignoring invalid AMBIENT_NIKKI_CHANNEL_IDS value %r.", value)
    return frozenset(channel_ids)


def _parse_lines(payload: Any) -> AmbientNikkiLines:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("the root must be a non-empty JSON object")
    categories: dict[str, AmbientNikkiCategory] = {}
    for name, raw_category in payload.items():
        if not isinstance(name, str) or not isinstance(raw_category, dict):
            raise ValueError("each category must be an object")
        triggers = _string_list(raw_category.get("triggers"), f"{name}.triggers")
        responses = _string_list(raw_category.get("responses"), f"{name}.responses")
        conditionals: list[tuple[str, tuple[str, ...]]] = []
        raw_conditionals = raw_category.get("conditional_responses", [])
        if not isinstance(raw_conditionals, list):
            raise ValueError(f"{name}.conditional_responses must be a list")
        for item in raw_conditionals:
            if not isinstance(item, dict) or not isinstance(item.get("requires"), str):
                raise ValueError(f"{name}.conditional_responses entries are invalid")
            requires = normalize_message_text(item["requires"])
            if not requires:
                raise ValueError(f"{name}.conditional response requires text")
            conditionals.append((requires, _string_list(item.get("responses"), f"{name}.conditional responses")))
        categories[name] = AmbientNikkiCategory(triggers, responses, tuple(conditionals))
    return AmbientNikkiLines(categories)


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    values = tuple(normalize_message_text(item) if "triggers" in label else item.strip() for item in value if isinstance(item, str))
    if len(values) != len(value) or not values or any(not item for item in values):
        raise ValueError(f"{label} must contain non-empty strings")
    return values


def _response_pool(category: AmbientNikkiCategory, normalized_content: str) -> tuple[str, ...]:
    for requires, responses in category.conditional_responses:
        if requires in normalized_content:
            return responses
    return category.responses


def _as_taipei_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TAIPEI_TIMEZONE)
    return value.astimezone(TAIPEI_TIMEZONE)
