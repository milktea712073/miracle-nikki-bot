"""Typed, source-independent records used by the local research tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ResearchMessage:
    """A locally exported Discord message; never sent over the network."""

    message_id: str
    author_id: str
    timestamp: datetime
    content: str
    channel_id: str = ""
    reply_to_message_id: str | None = None
    is_bot: bool = False

    @property
    def month(self) -> str:
        return self.timestamp.strftime("%Y-%m")


@dataclass(frozen=True)
class ReplyEvidence:
    text: str
    author_key: str
    delay_seconds: float
    direct_reply: bool
    flags: tuple[str, ...] = ()


@dataclass
class Candidate:
    text: str
    normalized_text: str
    frequency: int
    message_count: int
    author_keys: set[str] = field(default_factory=set)
    months: set[str] = field(default_factory=set)
    examples: list[ResearchMessage] = field(default_factory=list)
    reply_evidence: list[ReplyEvidence] = field(default_factory=list)
    score: float = 0.0
    category: str = "needs_review"
    flags: set[str] = field(default_factory=set)
    burst_months: list[str] = field(default_factory=list)

    @property
    def first_seen(self) -> str | None:
        return min(self.months) if self.months else None

    @property
    def last_seen(self) -> str | None:
        return max(self.months) if self.months else None
