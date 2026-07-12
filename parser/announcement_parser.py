"""First-pass, conservative rule-based parser for Miracle Nikki announcements."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from parser.models import ParseDraft, SuitCandidate


TAIPEI = ZoneInfo("Asia/Taipei")
RERUN_KEYWORDS = ("\u5fa9\u523b", "\u5fa9\u958b", "\u518d\u6b21\u767b\u5834")
DEBUT_KEYWORDS = ("\u9996\u6b21", "\u5168\u65b0", "\u521d\u6b21")
SUIT_CONTEXT_KEYWORDS = ("\u53ef\u7372\u5f97", "\u53ef\u8d0f\u5f97", "\u7372\u5f97", "\u6545\u4e8b\u5957\u88dd", "\u7cbe\u7dfb\u5957\u88dd", "\u96c6\u9f4a")
SUIT_GENERIC_NAMES = {"\u5957\u88dd", "\u90e8\u4ef6", "\u6d3b\u52d5", "\u734e\u52f5", "\u5fa9\u523b", "\u5957\u88dd\u90e8\u4ef6"}
SUIT_RESOURCE_NAMES = {"\u9ad4\u529b", "\u91d1\u5e63", "\u947d\u77f3", "\u661f\u5149\u5e63", "\u661f\u947d", "\u6750\u6599"}
SUIT_FUNCTION_NAMES = {"\u4e00\u9375\u88fd\u8863", "\u514d\u8cbb\u6b21\u6578", "\u9ede\u64ca\u9818\u53d6", "\u524d\u5f80\u6d3b\u52d5"}
SUIT_PART_PREFIXES = tuple(
    "\u4e0b\u88dd\u00b7 \u4e0a\u8863\u00b7 \u9023\u8863\u88d9\u00b7 \u978b\u5b50\u00b7 \u9aee\u578b\u00b7 \u599d\u5bb9\u00b7 \u982d\u98fe\u00b7 \u896a\u5b50\u00b7 \u5916\u5957\u00b7 \u624b\u6301\u00b7 \u9818\u98fe\u00b7 \u8033\u98fe\u00b7 \u624b\u98fe\u00b7 \u8170\u98fe\u00b7 \u7279\u6b8a\u00b7".split()
)
TITLE_PREFIX = re.compile(r"^\s*(?:\u3010[^\u3011]+\u3011)\s*")
TITLE_SUFFIX = re.compile(r"\s*(?:\u9650\u6642\u5fa9\u958b|\u5fa9\u523b|\u518d\u6b21\u767b\u5834|\u9996\u6b21|\u5168\u65b0|\u521d\u6b21)\s*$")
CHINESE_PERIOD = re.compile(
    r"(\d{4})\u5e74(\d{1,2})\u6708(\d{1,2})\u65e5(\d{1,2}):(\d{2})\s*[-\u2013\uff5e~]\s*"
    r"(\d{4})\u5e74(\d{1,2})\u6708(\d{1,2})\u65e5(\d{1,2}):(\d{2})"
)
SLASH_PERIOD = re.compile(
    r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})\s*[-\u2013\uff5e~]\s*"
    r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})"
)


def first_nonempty_line(content: str) -> str | None:
    return next((line.strip() for line in content.splitlines() if line.strip()), None)


def parse_period_type(title: str | None, content: str) -> str:
    text = "\n".join(filter(None, [title, content]))
    if any(keyword in text for keyword in RERUN_KEYWORDS):
        return "rerun"
    if any(keyword in text for keyword in DEBUT_KEYWORDS):
        return "debut"
    return "unknown"


def parse_event_name(title: str | None) -> str | None:
    if not title:
        return None
    name = TITLE_SUFFIX.sub("", TITLE_PREFIX.sub("", title)).strip()
    return name or None


def parse_period(content: str) -> tuple[str | None, str | None]:
    for pattern in (CHINESE_PERIOD, SLASH_PERIOD):
        match = pattern.search(content)
        if match is not None:
            values = [int(value) for value in match.groups()]
            return (
                datetime(*values[:5], tzinfo=TAIPEI).isoformat(),
                datetime(*values[5:], tzinfo=TAIPEI).isoformat(),
            )
    return None, None


def is_valid_suit_name(name: str) -> bool:
    """Reject UI labels, resources, and individual clothing parts."""
    normalized = name.strip()
    invalid = SUIT_GENERIC_NAMES | SUIT_RESOURCE_NAMES | SUIT_FUNCTION_NAMES
    if not normalized or normalized.isdecimal() or normalized in invalid:
        return False
    if normalized.startswith(SUIT_PART_PREFIXES):
        return False
    parts = [part.strip() for part in re.split(r"[\u3001,\uff0c/]", normalized) if part.strip()]
    return bool(parts) and not all(
        part.isdecimal() or part in invalid or part.startswith(SUIT_PART_PREFIXES)
        for part in parts
    )


def parse_suits(content: str) -> list[SuitCandidate]:
    """Return only bracketed names in an explicit full-suit acquisition context."""
    suits: list[SuitCandidate] = []
    seen: set[str] = set()
    for match in re.finditer(r"\u3010([^\u3011]+)\u3011", content):
        name = match.group(1).strip()
        context = content[max(0, match.start() - 48) : match.end() + 32]
        if name in seen or not is_valid_suit_name(name):
            continue
        if not any(keyword in context for keyword in SUIT_CONTEXT_KEYWORDS):
            continue
        seen.add(name)
        suits.append(SuitCandidate(name=name, confidence=0.9))
    return suits


def classify_content(title: str | None, content: str, has_suits: bool) -> str:
    """Classify posts so non-activity notices are retained but not made events."""
    text = "\n".join(filter(None, [title, content]))
    if any(word in text for word in ("\u684c\u5e03", "\u58c1\u7d19", "\u684c\u5e03\u5957\u7d44")):
        return "wallpaper"
    if any(word in text for word in ("\u7dad\u8b77", "\u958b\u6a5f", "\u7248\u672c\u66f4\u65b0", "\u7cfb\u7d71\u66f4\u65b0")):
        return "system"
    if has_suits:
        return "suit_event"
    if "\u5957\u88dd" in text and any(
        word in text for word in ("\u6d3b\u52d5\u6642\u9593", "\u9650\u6642", "\u958b\u653e", "\u958b\u555f")
    ):
        return "suit_event"
    if any(word in text for word in ("\u6d3b\u52d5\u6642\u9593", "\u9650\u6642", "\u5fa9\u523b", "\u958b\u653e", "\u958b\u555f")):
        return "event"
    if any(word in text for word in ("\u767b\u5165", "\u798f\u5229", "\u514d\u8cbb\u8d08\u9001")):
        return "welfare"
    if "\u516c\u544a" in text:
        return "notice"
    return "other"


def parse_announcement(content: str) -> ParseDraft:
    title = first_nonempty_line(content)
    start_at, end_at = parse_period(content)
    suits = parse_suits(content)
    notes: list[str] = []
    if start_at is None:
        notes.append("No supported activity date range was found.")
    content_type = classify_content(title, content, bool(suits))
    if content_type == "suit_event" and not suits:
        notes.append("No high-confidence suit candidates were found.")
    return ParseDraft(
        title=title,
        content_type_candidate=content_type,
        event_name_candidate=parse_event_name(title),
        official_series_candidate=None,
        period_type_candidate=parse_period_type(title, content),
        start_at_candidate=start_at,
        end_at_candidate=end_at,
        player_category_candidate=None,
        acquisition_method_candidate=None,
        confidence=0.9 if suits else (0.7 if title else 0.3),
        parser_notes=" ".join(notes) or None,
        suits=suits,
    )
