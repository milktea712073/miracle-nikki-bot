"""Context extraction that never exposes message or Discord user IDs."""

from __future__ import annotations

from collections.abc import Iterable

from .models import ResearchMessage
from .privacy import redact_text


def kwic_examples(messages: Iterable[ResearchMessage], phrase: str, *, context_chars: int, maximum: int) -> list[tuple[str, str]]:
    examples: list[tuple[str, str]] = []
    seen: set[str] = set()
    for message in messages:
        start = 0
        while len(examples) < maximum:
            index = message.content.find(phrase, start)
            if index < 0:
                break
            left = max(0, index - context_chars)
            right = min(len(message.content), index + len(phrase) + context_chars)
            excerpt, _private = redact_text(message.content[left:right], max_length=context_chars * 2 + len(phrase) + 12)
            highlighted = excerpt.replace(phrase, f"**{phrase}**", 1)
            if highlighted not in seen:
                examples.append((message.month, highlighted))
                seen.add(highlighted)
            start = index + len(phrase)
        if len(examples) >= maximum:
            break
    return examples
