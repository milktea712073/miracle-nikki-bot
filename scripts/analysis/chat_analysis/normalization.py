"""Conservative normalization used only for counting candidate phrases."""

from __future__ import annotations

import re
import unicodedata


URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"<(?:(?:@&?|#)\d+|a?:[A-Za-z0-9_]+:\d+)>")
WHITESPACE_RE = re.compile(r"\s+")
REPEATED_PUNCTUATION_RE = re.compile(r"([!?！？。…])\1+")


def normalize_for_analysis(value: str) -> str:
    """Normalize form and volatile Discord syntax without reordering Chinese text."""
    text = unicodedata.normalize("NFKC", value)
    text = URL_RE.sub("[網址]", text)
    text = MENTION_RE.sub("[提及]", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return REPEATED_PUNCTUATION_RE.sub(r"\1", text)


def normalize_phrase(value: str) -> str:
    return normalize_for_analysis(value).strip(" \t\r\n，。！？!?、:：;；（）()[]【】<>《》\"'")


def is_emoji_or_punctuation_only(value: str) -> bool:
    meaningful = [
        character
        for character in value
        if character.isalnum() or "\u4e00" <= character <= "\u9fff"
    ]
    return not meaningful


def is_chinese(character: str) -> bool:
    return "\u4e00" <= character <= "\u9fff"
