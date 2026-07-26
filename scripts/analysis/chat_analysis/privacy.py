"""Remove sensitive identifiers before a candidate is written to a report."""

from __future__ import annotations

import re

from .normalization import MENTION_RE, URL_RE


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?886[- ]?)?0?9\d{2}[- ]?\d{3}[- ]?\d{3}(?!\d)")
ADDRESS_RE = re.compile(r"(?:台[北中南東西]市|[\u4e00-\u9fff]{2,4}[縣市])[\u4e00-\u9fff\d]{2,20}(?:路|街|巷|弄|號)")


def redact_text(value: str, *, max_length: int = 180) -> tuple[str, bool]:
    """Return a report-safe excerpt and whether private syntax was detected."""
    private = False
    for expression, replacement in (
        (URL_RE, "[網址]"),
        (MENTION_RE, "[提及]"),
        (EMAIL_RE, "[信箱]"),
        (PHONE_RE, "[電話]"),
        (ADDRESS_RE, "[地址]"),
    ):
        value, substitutions = expression.subn(replacement, value)
        private = private or substitutions > 0
    value = " ".join(value.split())
    if len(value) > max_length:
        value = value[: max_length - 1].rstrip() + "…"
    return value, private


def anonymize_authors(author_ids: list[str]) -> dict[str, str]:
    """Keep stable anonymous labels based only on first sorted appearance."""
    labels: dict[str, str] = {}
    for author_id in author_ids:
        if author_id not in labels:
            labels[author_id] = f"player_{len(labels) + 1}"
    return labels
