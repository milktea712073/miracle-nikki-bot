"""Source-neutral DTOs for historical official-announcement search."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnnouncementSearchResult:
    """One raw official announcement, regardless of the SQLite store that supplied it."""

    source_kind: str
    source_record_id: int
    source: str
    region: str | None
    external_id: str
    title: str
    canonical_url: str
    published_at: str | None
    content_text: str
    image_urls: tuple[str, ...]

    @property
    def announcement_id(self) -> int | None:
        """Compatibility alias for callers that only handle v2 announcement rows."""
        return self.source_record_id if self.source_kind == "announcement" else None


@dataclass(frozen=True, slots=True)
class AnnouncementSearchPage:
    """A bounded search result plus whether additional matching notices remain."""

    results: tuple[AnnouncementSearchResult, ...]
    has_more: bool
