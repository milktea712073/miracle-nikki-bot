"""Pure decision flow for low-frequency Ambient Nikki skill events."""

from __future__ import annotations

import logging
import os
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .skills import render_general_event, render_sleep_event
from .state import AmbientNikkiState


LOGGER = logging.getLogger(__name__)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
DEFAULT_TRIGGER_RATE = 0.03
DEFAULT_SLEEP_TRIGGER_RATE = 0.08
DEFAULT_COOLDOWN_MINUTES = 30


@dataclass(frozen=True)
class AmbientNikkiSettings:
    enabled: bool
    trigger_rate: float
    sleep_trigger_rate: float
    cooldown_minutes: int
    channel_ids: frozenset[int]

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        logger: logging.Logger = LOGGER,
    ) -> "AmbientNikkiSettings":
        values = os.environ if environment is None else environment
        return cls(
            enabled=_load_boolean(values, "AMBIENT_NIKKI_ENABLED", False, logger),
            trigger_rate=_load_probability(values, "AMBIENT_NIKKI_TRIGGER_RATE", DEFAULT_TRIGGER_RATE, logger),
            sleep_trigger_rate=_load_probability(
                values, "AMBIENT_NIKKI_SLEEP_TRIGGER_RATE", DEFAULT_SLEEP_TRIGGER_RATE, logger
            ),
            cooldown_minutes=_load_nonnegative_integer(
                values, "AMBIENT_NIKKI_COOLDOWN_MINUTES", DEFAULT_COOLDOWN_MINUTES, logger
            ),
            channel_ids=_load_channel_ids(values, logger),
        )


@dataclass(frozen=True)
class AmbientEvent:
    text: str


class AmbientNikkiService:
    """Select at most one skill per eligible message and record only sends."""

    def __init__(
        self,
        settings: AmbientNikkiSettings,
        *,
        state: AmbientNikkiState | None = None,
        random_value: Callable[[], float] = random.random,
        choose_copy: Callable[[tuple[str, ...]], str] = random.choice,
    ) -> None:
        self.settings = settings
        self.state = state or AmbientNikkiState()
        self.random_value = random_value
        self.choose_copy = choose_copy

    def skip_reason(
        self,
        *,
        guild_id: int | None,
        channel_id: int | None,
        author_is_bot: bool,
        is_webhook: bool,
        is_system: bool,
    ) -> str | None:
        if not self.settings.enabled:
            return "disabled"
        if guild_id is None:
            return "direct_message"
        if not self.settings.channel_ids or channel_id not in self.settings.channel_ids:
            return "channel_not_allowed"
        if author_is_bot:
            return "author_bot"
        if is_webhook:
            return "webhook"
        if is_system:
            return "system_message"
        return None

    def decide(
        self,
        *,
        guild_id: int,
        channel_id: int,
        target: str,
        now: datetime,
    ) -> tuple[AmbientEvent | None, str | None]:
        """Run independent sleep/general chance checks without mutating state."""
        localized_now = _as_taipei_time(now)
        if self.state.is_cooling_down(guild_id, localized_now, self.settings.cooldown_minutes):
            return None, "cooldown"
        if 2 <= localized_now.hour <= 5 and self.random_value() < self.settings.sleep_trigger_rate:
            return AmbientEvent(render_sleep_event(target, choose=self.choose_copy)), None
        if self.random_value() < self.settings.trigger_rate:
            return AmbientEvent(render_general_event(target, choose=self.choose_copy)), None
        return None, "probability"

    def record_success(self, guild_id: int, now: datetime) -> None:
        self.state.record_success(guild_id, _as_taipei_time(now))


def display_target(author: object) -> str:
    """Use a display label only; Discord mention parsing remains disabled by sender."""
    for attribute in ("display_name", "name"):
        value = getattr(author, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "玩家"


def _load_boolean(values: Mapping[str, str], name: str, default: bool, logger: logging.Logger) -> bool:
    value = values.get(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    logger.warning("%s is invalid; using safe default %s.", name, default)
    return default


def _load_probability(values: Mapping[str, str], name: str, default: float, logger: logging.Logger) -> float:
    try:
        parsed = float(values.get(name, "") or default)
    except ValueError:
        parsed = -1.0
    if 0 <= parsed <= 1:
        return parsed
    logger.warning("%s is invalid; using safe default %s.", name, default)
    return default


def _load_nonnegative_integer(values: Mapping[str, str], name: str, default: int, logger: logging.Logger) -> int:
    try:
        parsed = int(values.get(name, "") or default)
    except ValueError:
        parsed = -1
    if parsed >= 0:
        return parsed
    logger.warning("%s is invalid; using safe default %s.", name, default)
    return default


def _load_channel_ids(values: Mapping[str, str], logger: logging.Logger) -> frozenset[int]:
    result: set[int] = set()
    for raw in values.get("AMBIENT_NIKKI_CHANNEL_IDS", "").split(","):
        value = raw.strip()
        if not value:
            continue
        if value.isdigit():
            result.add(int(value))
        else:
            logger.warning("Ignoring invalid AMBIENT_NIKKI_CHANNEL_IDS value %r.", value)
    return frozenset(result)


def _as_taipei_time(value: datetime) -> datetime:
    return value.replace(tzinfo=TAIPEI_TIMEZONE) if value.tzinfo is None else value.astimezone(TAIPEI_TIMEZONE)
