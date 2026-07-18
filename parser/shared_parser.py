"""Source-neutral parser adapter for one structural notice section."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from content.section_splitter import NoticeSection
from knowledge.story_event_reference import StoryEventMatch, match_story_events
from parser.announcement_parser import normalize_source_event_title, parse_announcement
from parser.models import ParseDraft


@dataclass(frozen=True, slots=True)
class SectionParseResult:
    """Existing parse output plus read-only story-reference evidence."""

    draft: ParseDraft
    story_event_matches: tuple[StoryEventMatch, ...]


def parse_notice_section(
    section: NoticeSection,
    *,
    raw_title: str | None = None,
    source: str | None = None,
    content_type_hint: str | None = None,
    parser: Callable[..., ParseDraft] = parse_announcement,
) -> SectionParseResult:
    """Parse only ``section.text`` while retaining the raw source title as context."""
    draft = parser(section.text) if content_type_hint is None else parser(section.text, content_type_hint=content_type_hint)
    if (
        source == "joybomb_archive"
        and section.heading is None
        and section.split_reason == "whole_notice"
    ):
        source_event_name = normalize_source_event_title(raw_title)
        if source_event_name is not None:
            draft = replace(draft, event_name_candidate=source_event_name)
    if raw_title and not draft.title:
        draft = replace(draft, title=raw_title)
    return SectionParseResult(
        draft=draft,
        story_event_matches=tuple(match_story_events(section.text)),
    )
