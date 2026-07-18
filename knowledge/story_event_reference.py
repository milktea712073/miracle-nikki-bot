"""Validated, side-effect-free reference data for Miracle Nikki story events."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_PATH = PROJECT_ROOT / "data" / "reference" / "story_events.json"
STORY_EVENT_CATEGORY = "故事套裝"
PeriodType = Literal["debut", "rerun", "wish_gate"]
MatchType = Literal["canonical", "alias"]
DATE_PATTERNS = {
    "month": re.compile(r"^\d{4}-(0[1-9]|1[0-2])$"),
    "day": re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
}
VALID_PERIOD_TYPES = frozenset({"debut", "rerun", "wish_gate"})


class StoryEventReferenceError(ValueError):
    """Raised when the maintained story-event reference is invalid."""


@dataclass(frozen=True, slots=True)
class StoryEventPeriod:
    type: PeriodType
    date: str
    date_precision: Literal["month", "day"]


@dataclass(frozen=True, slots=True)
class StoryEvent:
    canonical_name: str
    aliases: tuple[str, ...]
    category: str
    periods: tuple[StoryEventPeriod, ...]


@dataclass(frozen=True, slots=True)
class StoryEventMatch:
    canonical_name: str
    matched_text: str
    match_type: MatchType
    category: str
    confidence: float


def _require_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not (normalized := value.strip()):
        raise StoryEventReferenceError(f"{field} must be a non-empty string")
    return normalized


def _parse_period(value: object, *, event_name: str, index: int) -> StoryEventPeriod:
    if not isinstance(value, dict):
        raise StoryEventReferenceError(f"{event_name}.periods[{index}] must be an object")

    period_type = _require_string(value.get("type"), field=f"{event_name}.periods[{index}].type")
    if period_type not in VALID_PERIOD_TYPES:
        raise StoryEventReferenceError(f"{event_name}.periods[{index}].type is invalid: {period_type}")

    precision = _require_string(
        value.get("date_precision"), field=f"{event_name}.periods[{index}].date_precision"
    )
    if precision not in DATE_PATTERNS:
        raise StoryEventReferenceError(
            f"{event_name}.periods[{index}].date_precision is invalid: {precision}"
        )

    date = _require_string(value.get("date"), field=f"{event_name}.periods[{index}].date")
    if not DATE_PATTERNS[precision].fullmatch(date):
        raise StoryEventReferenceError(
            f"{event_name}.periods[{index}].date does not match {precision}: {date}"
        )

    return StoryEventPeriod(type=period_type, date=date, date_precision=precision)


def _parse_event(value: object, *, index: int, seen_names: set[str]) -> StoryEvent:
    if not isinstance(value, dict):
        raise StoryEventReferenceError(f"events[{index}] must be an object")

    canonical_name = _require_string(value.get("canonical_name"), field=f"events[{index}].canonical_name")
    if canonical_name in seen_names:
        raise StoryEventReferenceError(f"duplicate canonical_name: {canonical_name}")
    seen_names.add(canonical_name)

    category = _require_string(value.get("category"), field=f"{canonical_name}.category")
    if category != STORY_EVENT_CATEGORY:
        raise StoryEventReferenceError(f"{canonical_name}.category must be {STORY_EVENT_CATEGORY}")

    raw_aliases = value.get("aliases")
    if not isinstance(raw_aliases, list) or not all(isinstance(alias, str) for alias in raw_aliases):
        raise StoryEventReferenceError(f"{canonical_name}.aliases must be a list of strings")
    aliases = tuple(alias.strip() for alias in raw_aliases if alias.strip())
    if len(set(aliases)) != len(aliases):
        raise StoryEventReferenceError(f"{canonical_name}.aliases contains duplicates")
    if canonical_name in aliases:
        raise StoryEventReferenceError(f"{canonical_name}.aliases cannot contain canonical_name")

    raw_periods = value.get("periods")
    if not isinstance(raw_periods, list) or not raw_periods:
        raise StoryEventReferenceError(f"{canonical_name}.periods must be a non-empty list")
    periods = tuple(_parse_period(period, event_name=canonical_name, index=period_index) for period_index, period in enumerate(raw_periods))

    return StoryEvent(
        canonical_name=canonical_name,
        aliases=aliases,
        category=category,
        periods=periods,
    )


def load_story_event_reference(path: Path | None = None) -> tuple[StoryEvent, ...]:
    """Load and validate the JSON reference without caching or mutating global state."""
    reference_path = path or DEFAULT_REFERENCE_PATH
    try:
        payload = json.loads(reference_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StoryEventReferenceError(f"reference file not found: {reference_path}") from error
    except json.JSONDecodeError as error:
        raise StoryEventReferenceError(f"invalid JSON in {reference_path}: {error.msg}") from error

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise StoryEventReferenceError("reference schema_version must be 1")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise StoryEventReferenceError("events must be a non-empty list")

    seen_names: set[str] = set()
    events = tuple(_parse_event(event, index=index, seen_names=seen_names) for index, event in enumerate(raw_events))

    seen_lookup_names: set[str] = set()
    for event in events:
        for lookup_name in (event.canonical_name, *event.aliases):
            if lookup_name in seen_lookup_names:
                raise StoryEventReferenceError(f"duplicate canonical or alias name: {lookup_name}")
            seen_lookup_names.add(lookup_name)
    return events


def find_story_event(name: str, events: Sequence[StoryEvent] | None = None) -> StoryEvent | None:
    """Find one event by an exact canonical name or exact alias."""
    normalized_name = name.strip()
    if not normalized_name:
        return None
    reference = events if events is not None else load_story_event_reference()
    for event in reference:
        if normalized_name == event.canonical_name or normalized_name in event.aliases:
            return event
    return None


def match_story_events(text: str, events: Sequence[StoryEvent] | None = None) -> list[StoryEventMatch]:
    """Return direct canonical or alias text matches without fuzzy matching."""
    if not isinstance(text, str) or not text:
        return []
    reference = events if events is not None else load_story_event_reference()
    matches: list[tuple[int, StoryEventMatch]] = []
    for event in reference:
        canonical_position = text.find(event.canonical_name)
        if canonical_position >= 0:
            matches.append(
                (
                    canonical_position,
                    StoryEventMatch(
                        canonical_name=event.canonical_name,
                        matched_text=event.canonical_name,
                        match_type="canonical",
                        category=event.category,
                        confidence=1.0,
                    ),
                )
            )
            continue
        for alias in event.aliases:
            alias_position = text.find(alias)
            if alias_position >= 0:
                matches.append(
                    (
                        alias_position,
                        StoryEventMatch(
                            canonical_name=event.canonical_name,
                            matched_text=alias,
                            match_type="alias",
                            category=event.category,
                            confidence=0.98,
                        ),
                    )
                )
                break
    return [match for _, match in sorted(matches, key=lambda item: (item[0], item[1].canonical_name))]
