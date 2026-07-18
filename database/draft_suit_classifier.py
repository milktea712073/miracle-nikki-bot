"""Conservative, read-only classification for already stored draft suit candidates."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal
import unicodedata

from parser.announcement_parser import (
    BRACKETED_SUIT_PATTERN,
    LEGACY_SUIT_PATTERNS,
    SUIT_FUNCTION_NAMES,
    SUIT_GENERIC_NAMES,
    SUIT_PART_PREFIXES,
    SUIT_RESOURCE_NAMES,
    has_high_confidence_suit_context,
    has_suit_acquisition_context,
    is_reward_enumeration,
    is_reward_item_name,
    is_valid_suit_name,
)


DraftSuitClassification = Literal["eligible", "reject", "review"]

# These are grammatical descriptors used around a suit name, not suit names
# themselves.  This deliberately remains small; uncertain names are review.
SUIT_NAME_DESCRIPTOR_FRAGMENTS = frozenset(
    {"\u7cbe\u7dfb", "\u7cbe\u7f8e", "\u6545\u4e8b", "\u5168\u65b0", "\u5fa9\u523b", "\u6210\u5c31", "\u6536\u96c6", "\u5c0d\u61c9"}
)


@dataclass(frozen=True, slots=True)
class SuitClassificationResult:
    classification: DraftSuitClassification
    reason: str


def normalize_suit_candidate(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").split())


def classify_stored_suit_candidate(
    name: str,
    section_text: str,
    *,
    event_name_candidate: str | None = None,
    section_heading: str | None = None,
) -> SuitClassificationResult:
    """Classify a candidate without changing Parser rules or stored draft rows.

    Rejections require direct evidence that a value is a resource, UI label,
    component, quantity, or the section's own activity name.  Everything else
    needs the same explicit suit context used by the Parser; uncertain values
    remain ``review`` rather than being discarded.
    """
    normalized = normalize_suit_candidate(name)
    invalid = SUIT_GENERIC_NAMES | SUIT_RESOURCE_NAMES | SUIT_FUNCTION_NAMES
    if not normalized:
        return SuitClassificationResult("reject", "empty candidate")
    if normalized.isdecimal() or re.fullmatch(r"[xX×*]?\s*\d+(?:\s*[xX×*])?", normalized):
        return SuitClassificationResult("reject", "pure number or quantity")
    if normalized in SUIT_RESOURCE_NAMES or is_reward_item_name(normalized, invalid):
        return SuitClassificationResult("reject", "resource, reward item, or UI label")
    if normalized in SUIT_GENERIC_NAMES or normalized in SUIT_FUNCTION_NAMES:
        return SuitClassificationResult("reject", "generic or function label")
    if normalized in SUIT_NAME_DESCRIPTOR_FRAGMENTS:
        return SuitClassificationResult("reject", "suit descriptor without a name")
    if normalized.startswith(("\u4e4b", "\u7684")) or normalized.endswith("\u7684"):
        return SuitClassificationResult("reject", "incomplete grammatical fragment")
    if re.search(r"\*\s*\d+$", normalized):
        return SuitClassificationResult("reject", "quantity expression")
    if normalized.startswith(SUIT_PART_PREFIXES):
        return SuitClassificationResult("reject", "individual clothing component")

    parts = [part.strip() for part in re.split(r"[、,/，]", normalized) if part.strip()]
    if is_reward_enumeration(parts, invalid):
        return SuitClassificationResult("reject", "resource or reward enumeration")
    if not is_valid_suit_name(normalized):
        return SuitClassificationResult("reject", "rejected by existing suit validation")

    comparable = normalize_suit_candidate(normalized)
    for activity_value, label in (
        (event_name_candidate, "event name"),
        (section_heading, "section heading"),
    ):
        if activity_value and comparable == normalize_suit_candidate(activity_value):
            return SuitClassificationResult("reject", f"matches the {label}")

    for match in BRACKETED_SUIT_PATTERN.finditer(section_text):
        matched_name = next(
            value for value in match.groupdict().values() if value is not None
        )
        if normalize_suit_candidate(matched_name) != comparable:
            continue
        if has_high_confidence_suit_context(section_text, match):
            return SuitClassificationResult("eligible", "explicit complete-suit context")
        if match.group("corner") is not None and has_suit_acquisition_context(section_text, match):
            return SuitClassificationResult("eligible", "acquisition sentence explicitly describes a suit")

    for pattern in LEGACY_SUIT_PATTERNS:
        for match in pattern.finditer(section_text):
            if normalize_suit_candidate(match.group("name")) == comparable:
                return SuitClassificationResult("eligible", "legacy acquisition format explicitly names a suit")

    return SuitClassificationResult("review", "no explicit complete-suit context in this section")
