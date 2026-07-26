"""Character n-gram and short-phrase mining without Chinese tokenization."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from .models import ResearchMessage
from .normalization import is_chinese, is_emoji_or_punctuation_only, normalize_phrase


def character_ngrams(content: str, minimum: int, maximum: int) -> Counter[str]:
    characters = "".join(character for character in content if is_chinese(character))
    counts: Counter[str] = Counter()
    for size in range(minimum, maximum + 1):
        counts.update(characters[index:index + size] for index in range(max(0, len(characters) - size + 1)))
    return counts


def mine_ngrams(messages: Iterable[ResearchMessage], minimum: int, maximum: int) -> dict[str, list[ResearchMessage]]:
    occurrences: dict[str, list[ResearchMessage]] = defaultdict(list)
    for message in messages:
        for phrase, count in character_ngrams(message.content, minimum, maximum).items():
            if not is_emoji_or_punctuation_only(phrase):
                occurrences[phrase].extend([message] * count)
    return dict(occurrences)


def repeated_short_phrases(messages: Iterable[ResearchMessage]) -> dict[str, list[ResearchMessage]]:
    occurrences: dict[str, list[ResearchMessage]] = defaultdict(list)
    for message in messages:
        phrase = normalize_phrase(message.content)
        if 2 <= len(phrase) <= 30 and not is_emoji_or_punctuation_only(phrase):
            occurrences[phrase].append(message)
    return dict(occurrences)


def suppress_overlapping_candidates(
    phrase_counts: Counter[str], *, ratio: float = 0.8
) -> list[str]:
    """Prefer a longer near-equally-frequent phrase over its short substring."""
    kept: list[str] = []
    for phrase, count in sorted(phrase_counts.items(), key=lambda item: (-len(item[0]), -item[1], item[0])):
        if any(phrase in longer and count <= phrase_counts[longer] / ratio for longer in kept):
            continue
        kept.append(phrase)
    return sorted(kept, key=lambda item: (-phrase_counts[item], -len(item), item))


def common_edge_patterns(phrases: Iterable[str]) -> tuple[Counter[str], Counter[str]]:
    prefixes: Counter[str] = Counter()
    suffixes: Counter[str] = Counter()
    for phrase in phrases:
        if len(phrase) >= 3:
            prefixes[phrase[:2]] += 1
            suffixes[phrase[-2:]] += 1
    return prefixes, suffixes
