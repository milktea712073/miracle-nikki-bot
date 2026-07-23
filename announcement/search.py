"""Pure formatting helpers for announcement-history search results."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from urllib.parse import urlsplit


SEARCH_EXCERPT_LENGTH = 180
LOGGER = logging.getLogger(__name__)
_OPENCC_CONVERTERS: tuple[object, ...] | None = None


def _get_opencc_converters() -> tuple[object, ...]:
    """Initialize OpenCC once, while preserving literal search if it is unavailable."""
    global _OPENCC_CONVERTERS
    if _OPENCC_CONVERTERS is not None:
        return _OPENCC_CONVERTERS
    try:
        from opencc import OpenCC

        _OPENCC_CONVERTERS = (OpenCC("t2s"), OpenCC("s2t"))
    except Exception:
        LOGGER.warning(
            "OpenCC is unavailable; announcement search will use literal keywords only.",
            exc_info=True,
        )
        _OPENCC_CONVERTERS = ()
    return _OPENCC_CONVERTERS


def normalize_search_text(value: str) -> str:
    """Collapse page-source whitespace into Discord-readable prose."""
    return re.sub(r"\s+", " ", value).strip()


def keyword_search_variants(keyword: str) -> tuple[str, ...]:
    """Return literal, Simplified, and Traditional variants without duplicates."""
    variants: list[str] = []
    normalized_keyword = keyword.strip()
    if normalized_keyword:
        variants.append(normalized_keyword)
    for converter in _get_opencc_converters():
        try:
            converted = converter.convert(normalized_keyword).strip()
        except Exception:
            LOGGER.warning("OpenCC keyword conversion failed; retaining available search variants.", exc_info=True)
            continue
        if converted and converted not in variants:
            variants.append(converted)
    return tuple(variants)


def build_search_excerpt(content: str, keyword: str, *, limit: int = SEARCH_EXCERPT_LENGTH) -> str | None:
    """Return a bounded excerpt centred on a body match, or the body opening for title matches."""
    normalized_content = normalize_search_text(content)
    normalized_keyword = normalize_search_text(keyword)
    if not normalized_content:
        return None
    if limit < 1:
        raise ValueError("limit must be positive")

    match_positions = [
        normalized_content.casefold().find(variant.casefold())
        for variant in keyword_search_variants(normalized_keyword)
    ]
    match_start = min(position for position in match_positions if position >= 0) if any(
        position >= 0 for position in match_positions
    ) else -1
    if match_start < 0:
        start = 0
    else:
        start = max(0, match_start - (limit // 2))
    end = min(len(normalized_content), start + limit)
    if end - start < limit and start > 0:
        start = max(0, end - limit)

    excerpt = normalized_content[start:end]
    if start > 0:
        excerpt = f"…{excerpt}"
    if end < len(normalized_content):
        excerpt = f"{excerpt}…"
    return excerpt


def first_valid_image_url(image_urls: Iterable[str]) -> str | None:
    """Return the first HTTP(S) URL suitable for a Discord embed image."""
    valid_urls = valid_image_urls(image_urls, limit=1)
    return valid_urls[0] if valid_urls else None


def valid_image_urls(image_urls: Iterable[str], *, limit: int | None = None) -> tuple[str, ...]:
    """Return distinct HTTP(S) image URLs in their original announcement order."""
    if limit is not None and limit < 1:
        return ()
    values: list[str] = []
    seen: set[str] = set()
    for image_url in image_urls:
        if not isinstance(image_url, str):
            continue
        candidate = image_url.strip()
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or candidate in seen:
            continue
        seen.add(candidate)
        values.append(candidate)
        if limit is not None and len(values) >= limit:
            break
    return tuple(values)
