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
HIGH_CONFIDENCE_SUIT_PREFIXES = (
    "\u5957\u88dd\u70ba",
    "\u6545\u4e8b\u5957\u88dd",
    "\u5168\u65b0\u5957\u88dd",
    "\u7cbe\u7dfb\u7bc0\u65e5\u5957\u88dd",
    "\u7cbe\u7dfb\u5957\u88dd",
    "\u6210\u5c31\u5957\u88dd",
    "\u6536\u96c6\u5957\u88dd",
    "\u5fa9\u523b\u5957\u88dd",
    "\u5957\u88dd",
)
HIGH_CONFIDENCE_SUIT_LIST_PREFIX = re.compile(
    r"(?:\u5957\u88dd\u70ba|\u6545\u4e8b\u5957\u88dd|\u5168\u65b0\u5957\u88dd|\u7cbe\u7dfb\u7bc0\u65e5\u5957\u88dd|"
    r"\u7cbe\u7dfb\u5957\u88dd|\u6210\u5c31\u5957\u88dd|\u6536\u96c6\u5957\u88dd|\u5fa9\u523b\u5957\u88dd|\u5957\u88dd)"
    r"\s*(?:\u3010[^\u3011]+\u3011\s*[\u3001\uff0c\u3001\u53ca\u548c\u8207]*)*$"
)
SUIT_GENERIC_NAMES = {"\u5957\u88dd", "\u90e8\u4ef6", "\u6d3b\u52d5", "\u734e\u52f5", "\u5fa9\u523b", "\u5957\u88dd\u90e8\u4ef6", "\u65b0\u589e"}
SUIT_RESOURCE_NAMES = {"\u9ad4\u529b", "\u91d1\u5e63", "\u947d\u77f3", "\u661f\u5149\u5e63", "\u661f\u947d", "\u661f\u66dc\u77f3", "\u6750\u6599"}
SUIT_FUNCTION_NAMES = {"\u4e00\u9375\u88fd\u8863", "\u514d\u8cbb\u6b21\u6578", "\u9ede\u64ca\u9818\u53d6", "\u524d\u5f80\u6d3b\u52d5"}
REWARD_ITEM_MARKERS = ("部件", "材料", "資源", "道具", "票券")
SUIT_PART_PREFIXES = tuple(
    "\u4e0b\u88dd\u00b7 \u4e0a\u8863\u00b7 \u9023\u8863\u88d9\u00b7 \u978b\u5b50\u00b7 \u9aee\u578b\u00b7 \u599d\u5bb9\u00b7 \u982d\u98fe\u00b7 \u896a\u5b50\u00b7 \u5916\u5957\u00b7 \u624b\u6301\u00b7 \u9818\u98fe\u00b7 \u8033\u98fe\u00b7 \u624b\u98fe\u00b7 \u8170\u98fe\u00b7 \u7279\u6b8a\u00b7".split()
)
TITLE_PREFIX = re.compile(r"^\s*(?:\u3010[^\u3011]+\u3011)\s*")
TITLE_SUFFIX = re.compile(r"\s*(?:\u9650\u6642\u5fa9\u958b|\u5fa9\u523b|\u518d\u6b21\u767b\u5834|\u9996\u6b21|\u5168\u65b0|\u521d\u6b21)\s*$")
GENERIC_SOURCE_TITLES = frozenset({
    "\u65b0\u805e\u516c\u544a",
    "\u516c\u544a",
    "\u6d3b\u52d5\u516c\u544a",
    "\u5b98\u65b9\u516c\u544a",
    "\u6d3b\u52d5",
    "\u6700\u65b0\u6d88\u606f",
    "\u5947\u8ff9\u6696\u6696",
    "\u5947\u8e5f\u6696\u6696",
})
EVENT_NAME_LABELS = ("\u6d3b\u52d5\u6642\u9593", "\u6d3b\u52d5\u5167\u5bb9", "\u6d3b\u52d5\u65b9\u5f0f", "\u6d3b\u52d5\u898f\u5247", "\u6ce8\u610f\u4e8b\u9805")
SOURCE_TITLE_CATEGORY_PREFIX = re.compile(
    r"^\s*(?:\u3010\s*(?:\u6d3b\u52d5|\u65b0\u805e|\u516c\u544a|\u5b98\u65b9\u516c\u544a|\u6700\u65b0\u6d88\u606f|\u7cfb\u7d71|\u7dad\u8b77|\u798f\u5229)\s*\u3011|"
    r"(?:\u6d3b\u52d5|\u65b0\u805e|\u516c\u544a|\u5b98\u65b9\u516c\u544a|\u6700\u65b0\u6d88\u606f)\s*[:\uff1a\-\u2014]?)\s*"
)
SOURCE_TITLE_DATE = re.compile(
    r"(?:20\d{2}\s*(?:[./-]|\u5e74)\s*\d{1,2}\s*(?:[./-]|\u6708)\s*\d{1,2}\s*(?:\u65e5)?)"
)
NEWSROOM_LEDE_MARKERS = ("\u5ba3\u5e03", "\u8868\u793a", "\u63a8\u51fa", "\u767b\u5834", "\u6b63\u5f0f", "\u5c07\u65bc")
NEWSROOM_LEDE_BRAND_MARKERS = ("\u4e3b\u6253", "\u624b\u6a5f\u904a\u6232", "\u6642\u5c1a\u63db\u88dd\u624b\u904a", "\u63db\u88dd\u984c\u6750")
BRACKETED_SUIT_PATTERN = re.compile(
    r"(?:\u3010(?P<corner>[^\u3011]+)\u3011|\uff3b(?P<fullwidth>[^\uff3d]+)\uff3d|\u300c(?P<quote>[^\u300d]+)\u300d)"
)
LEGACY_SUIT_PATTERNS = (
    re.compile(
        r"(?:\u53ef\u7372\u5f97|\u53ef\u8d0f\u5f97|\u7372\u5f97|\u96c6\u9f4a)\s*"
        r"(?:\u5168\u65b0|\u7cbe\u7dfb|\u6545\u4e8b|\u6210\u5c31|\u6536\u96c6|\u5fa9\u523b)?\s*"
        r"(?P<name>[^\n\uff0c\u3002\uff1b\uff1a\u3001\u3010\u3011\uff3b\uff3d\u300c\u300d]{2,30}?)\s*\u5957\u88dd(?=$|[\s\u3002\uff01!\uff0c\u3001\uff1b])"
    ),
    re.compile(
        r"(?:\u5b8c\u6210\u6d3b\u52d5|\u5b8c\u6210\u4efb\u52d9)(?:\u5373\u53ef)?(?:\u53d6\u5f97|\u7372\u5f97)\s*"
        r"(?:\u5168\u65b0|\u7cbe\u7dfb|\u6545\u4e8b|\u6210\u5c31|\u6536\u96c6|\u5fa9\u523b)?\s*"
        r"(?P<name>[^\n\uff0c\u3002\uff1b\uff1a\u3001\u3010\u3011\uff3b\uff3d\u300c\u300d]{2,30}?)\s*\u5957\u88dd(?=$|[\s\u3002\uff01!\uff0c\u3001\uff1b])"
    ),
)
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


def normalize_source_event_title(raw_title: str | None) -> str | None:
    """Return a usable source title for a whole-notice event name.

    This deliberately removes only presentation metadata that JoyBomb places
    around a notice title. It never truncates prose: an overlong or generic
    result remains unusable instead of becoming a misleading partial name.
    """
    if not raw_title:
        return None
    title = SOURCE_TITLE_CATEGORY_PREFIX.sub("", str(raw_title).strip())
    title = SOURCE_TITLE_DATE.sub(" ", title)
    title = re.sub(r"\s+", " ", title).strip(" -\u2014:\uff1a")
    if not title or title in GENERIC_SOURCE_TITLES or is_newsroom_lede(title):
        return None
    return title


def is_newsroom_lede(value: str | None) -> bool:
    """Reject prose-like press-release leads as event-name candidates."""
    if not value:
        return True
    text = value.strip()
    if len(text) > 80:
        return True
    if any(marker in text for marker in NEWSROOM_LEDE_BRAND_MARKERS):
        return True
    if any(marker in text for marker in NEWSROOM_LEDE_MARKERS) and (
        "\uff0c" in text or "\u3002" in text or len(text) > 45
    ):
        return True
    return text.count("\uff0c") >= 2 or "\u3002" in text


def parse_period_type(title: str | None, content: str) -> str:
    text = "\n".join(filter(None, [title, content]))
    if any(keyword in text for keyword in RERUN_KEYWORDS):
        return "rerun"
    if any(keyword in text for keyword in DEBUT_KEYWORDS):
        return "debut"
    return "unknown"


def parse_event_name(title: str | None, content: str | None = None) -> str | None:
    if not title:
        return None
    name = TITLE_SUFFIX.sub("", TITLE_PREFIX.sub("", title)).strip()
    if not name or name in GENERIC_SOURCE_TITLES or is_newsroom_lede(name):
        return find_event_name_in_content(content, title)
    return name


def find_event_name_in_content(content: str | None, source_title: str) -> str | None:
    """Find a conservative body heading when the source title is generic."""
    if not content:
        return None
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        candidate = TITLE_SUFFIX.sub("", TITLE_PREFIX.sub("", line)).strip()
        if (
            not candidate
            or candidate == source_title
            or candidate in GENERIC_SOURCE_TITLES
            or candidate.startswith(EVENT_NAME_LABELS)
            or len(candidate) > 60
        ):
            continue
        following = "\n".join(lines[index + 1 : index + 5])
        if "\u6d3b\u52d5" in candidate or any(label in following for label in EVENT_NAME_LABELS):
            return candidate
    return None


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
    if not normalized or normalized.isdecimal() or is_reward_item_name(normalized, invalid):
        return False
    if re.search(r"\*\s*\d+$", normalized):
        return False
    if normalized.startswith(SUIT_PART_PREFIXES):
        return False
    parts = [part.strip() for part in re.split(r"[\u3001,\uff0c/]", normalized) if part.strip()]
    if is_reward_enumeration(parts, invalid):
        return False
    return bool(parts) and not all(
        part.isdecimal() or is_reward_item_name(part, invalid) or part.startswith(SUIT_PART_PREFIXES)
        for part in parts
    )


def is_reward_item_name(name: str, invalid: set[str]) -> bool:
    """Identify a single resource or reward item, not a complete suit name."""
    return name in invalid or any(marker in name for marker in REWARD_ITEM_MARKERS)


def is_reward_enumeration(parts: list[str], invalid: set[str]) -> bool:
    """Reject bracketed reward lists while preserving lists of actual suit names."""
    if len(parts) < 2:
        return False
    reward_items = sum(
        part.isdecimal() or is_reward_item_name(part, invalid) or part.startswith(SUIT_PART_PREFIXES)
        for part in parts
    )
    return reward_items * 2 > len(parts)


def has_high_confidence_suit_context(content: str, match: re.Match[str]) -> bool:
    """Recognize official formats that explicitly attach a name to a full suit."""
    prefix = content[max(0, match.start() - 48) : match.start()].rstrip()
    suffix = content[match.end() : match.end() + 32].lstrip()
    return (
        prefix.endswith(HIGH_CONFIDENCE_SUIT_PREFIXES)
        or HIGH_CONFIDENCE_SUIT_LIST_PREFIX.search(prefix) is not None
        or suffix.startswith("\u5957\u88dd")
    )


def has_suit_acquisition_context(content: str, match: re.Match[str]) -> bool:
    """Keep broad acquisition wording only when it also describes a suit."""
    sentence_start = max(
        content.rfind(separator, 0, match.start())
        for separator in ("\n", "\u3002", "\uff01", "\uff1f", "\uff1b")
    )
    sentence_end_candidates = [
        position
        for separator in ("\n", "\u3002", "\uff01", "\uff1f", "\uff1b")
        if (position := content.find(separator, match.end())) != -1
    ]
    sentence_end = min(sentence_end_candidates, default=len(content))
    sentence = content[sentence_start + 1 : sentence_end]
    return re.search(r"\u5957\u88dd(?!\s*\u90e8\u4ef6)", sentence) is not None and any(
        keyword in sentence for keyword in SUIT_CONTEXT_KEYWORDS
    )


def parse_suits(content: str) -> list[SuitCandidate]:
    """Return only names explicitly described as complete suits in the source text."""
    suits: list[SuitCandidate] = []
    seen: set[str] = set()

    def add(name: str, confidence: float) -> None:
        normalized = name.strip()
        if normalized in seen or not is_valid_suit_name(normalized):
            return
        seen.add(normalized)
        suits.append(SuitCandidate(name=normalized, confidence=confidence))

    for match in BRACKETED_SUIT_PATTERN.finditer(content):
        name = next(value for value in match.groupdict().values() if value is not None).strip()
        if name in seen or not is_valid_suit_name(name):
            continue
        if has_high_confidence_suit_context(content, match):
            add(name, 1.0)
        elif match.group("corner") is not None and has_suit_acquisition_context(content, match):
            add(name, 0.9)

    for pattern in LEGACY_SUIT_PATTERNS:
        for match in pattern.finditer(content):
            add(match.group("name"), 0.9)
    return suits


EMOJI_CONTENT_TYPE_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("wallpaper", ("\U0001f5bc", "\U0001f3a8")),
    ("system", ("\U0001f6e0", "\u2699", "\U0001f527")),
    ("suit_event", ("\U0001f457",)),
    ("welfare", ("\U0001f381", "\u26f1", "\U0001f389")),
    ("notice", ("\U0001f4e2", "\U0001f4e3")),
)


def classify_content_from_text(title: str | None, content: str, has_suits: bool) -> str:
    """Apply the established keyword classification rules without emoji signals."""
    text = "\n".join(filter(None, [title, content]))
    if any(word in text for word in ("\u684c\u5e03", "\u58c1\u7d19", "\u684c\u5e03\u5957\u7d44")):
        return "wallpaper"
    if has_suits:
        return "suit_event"
    if "\u5957\u88dd" in text and any(
        word in text for word in ("\u6d3b\u52d5\u6642\u9593", "\u9650\u6642", "\u958b\u653e", "\u958b\u555f")
    ):
        return "suit_event"
    if any(word in text for word in ("\u6d3b\u52d5\u6642\u9593", "\u9650\u6642", "\u5fa9\u523b", "\u958b\u653e", "\u958b\u555f")):
        return "event"
    if any(word in text for word in ("\u7dad\u8b77", "\u958b\u6a5f", "\u7248\u672c\u66f4\u65b0", "\u7cfb\u7d71\u66f4\u65b0")):
        return "system"
    if any(word in text for word in ("\u767b\u5165", "\u798f\u5229", "\u514d\u8cbb\u8d08\u9001")):
        return "welfare"
    if "\u516c\u544a" in text:
        return "notice"
    return "other"


def classify_content_from_emoji(title: str | None, content: str) -> str:
    """Classify only from emoji placed in the title or opening announcement text."""
    opening = "\n".join(filter(None, [title, content[:160]])).replace("\ufe0f", "")
    for content_type, emojis in EMOJI_CONTENT_TYPE_SIGNALS:
        if any(emoji in opening for emoji in emojis):
            return content_type
    return "other"


def classify_content(title: str | None, content: str, has_suits: bool) -> str:
    """Classify posts with keywords first and title emoji as a conservative fallback."""
    text_result = classify_content_from_text(title, content, has_suits)
    if text_result != "other":
        return text_result
    return classify_content_from_emoji(title, content)


def parse_announcement(content: str, *, content_type_hint: str | None = None) -> ParseDraft:
    """Parse announcement text, optionally honoring a source-neutral category hint."""
    title = first_nonempty_line(content)
    start_at, end_at = parse_period(content)
    suits = parse_suits(content)
    notes: list[str] = []
    if start_at is None:
        notes.append("No supported activity date range was found.")
    content_type = content_type_hint or classify_content(title, content, bool(suits))
    if content_type == "suit_event" and not suits:
        notes.append("No high-confidence suit candidates were found.")
    return ParseDraft(
        title=title,
        content_type_candidate=content_type,
        event_name_candidate=parse_event_name(title, content),
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
