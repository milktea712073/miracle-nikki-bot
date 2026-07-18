"""Conservatively split raw announcement text into structural sections."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Literal


SPLITTER_VERSION = "section-split-v1"
SplitReason = Literal["whole_notice", "explicit_activity", "explicit_category"]

_ACTIVITY_LABEL = r"\u6d3b\u52d5\s*(?:[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+|\d+)"
_EMOJI_PREFIX = r"(?:[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0E\uFE0F]\s*)*"
_BRACKETED_ACTIVITY = re.compile(
    rf"^\s*{_EMOJI_PREFIX}\u3010\s*({_ACTIVITY_LABEL})\s*\u3011\s*(.*)$"
)
_DELIMITED_ACTIVITY = re.compile(
    rf"^\s*{_EMOJI_PREFIX}({_ACTIVITY_LABEL})\s*[\u3001:\uff1a]\s*(.*)$"
)
_BARE_ACTIVITY = re.compile(rf"^\s*{_EMOJI_PREFIX}({_ACTIVITY_LABEL})\s*$")
_CATEGORY_HEADING = re.compile(
    r"^\s*(?:\u3010\s*)?(\u5132\u503c(?:\u6d3b\u52d5)?|\u767b\u5165\u9001|\u798f\u5229(?:\u6d3b\u52d5)?|\u7dad\u8b77|\u7cfb\u7d71(?:\u516c\u544a)?|\u5546\u57ce\u66f4\u65b0)(?:\s*\u3011)?\s*(?:[:\uff1a]\s*(.*))?\s*$"
)


def _normalize_for_hash(value: str | None) -> str:
    """Normalize insignificant whitespace while preserving source-text order."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.strip() for line in normalized.split("\n") if line.strip())


def normalize_heading(heading: str | None) -> str | None:
    normalized = _normalize_for_hash(heading)
    return re.sub(r"\s+", " ", normalized) if normalized else None


def calculate_section_hash(heading: str | None, text: str) -> str:
    """Return a deterministic content fingerprint for section-level identity."""
    payload = f"heading={normalize_heading(heading) or ''}\ntext={_normalize_for_hash(text)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class NoticeSection:
    """One contiguous, source-text section identified without semantic parsing."""

    section_index: int
    heading: str | None
    text: str
    start_line: int
    end_line: int
    split_reason: SplitReason
    section_hash: str
    splitter_version: str = SPLITTER_VERSION
    normalized_heading: str | None = None

    @property
    def index(self) -> int:
        """Backward-compatible display alias used by existing diagnostics."""
        return self.section_index

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SectionSplitResult:
    """Common diagnostic output for Facebook, JoyBomb, and future sources."""

    source: str
    source_post_id: str | None
    raw_post_id: int | None
    title: str | None
    section_count: int
    sections: list[NoticeSection]
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "source_post_id": self.source_post_id,
            "raw_post_id": self.raw_post_id,
            "title": self.title,
            "section_count": self.section_count,
            "sections": [section.to_dict() for section in self.sections],
            "warnings": self.warnings,
        }


def _make_section(
    *,
    section_index: int,
    heading: str | None,
    text: str,
    start_line: int,
    end_line: int,
    split_reason: SplitReason,
) -> NoticeSection:
    return NoticeSection(
        section_index=section_index,
        heading=heading,
        text=text,
        start_line=start_line,
        end_line=end_line,
        split_reason=split_reason,
        section_hash=calculate_section_hash(heading, text),
        normalized_heading=normalize_heading(heading),
    )


def _title_from_content(content: str) -> str | None:
    return next((line.strip() for line in content.splitlines() if line.strip()), None)


def _has_substantive_preamble(value: str) -> bool:
    """Ignore whitespace-only extraction residue without judging real prose."""
    return any(line.strip().strip("\ufeff\u200b") for line in value.splitlines())


def _heading_for_line(line: str) -> tuple[str, SplitReason, str | None] | None:
    """Return only explicit structural headings, avoiding semantic splitting."""
    for pattern in (_BRACKETED_ACTIVITY, _DELIMITED_ACTIVITY, _BARE_ACTIVITY):
        match = pattern.match(line)
        if match is not None:
            inline_text = match.group(2).strip() if match.lastindex and match.lastindex >= 2 and match.group(2) else None
            return match.group(1).strip(), "explicit_activity", inline_text
    match = _CATEGORY_HEADING.match(line)
    if match is not None:
        inline_text = match.group(2).strip() if match.group(2) else None
        return match.group(1).strip(), "explicit_category", inline_text
    return None


def split_notice_sections(
    content: str,
    *,
    source: str,
    source_post_id: str | None = None,
    raw_post_id: int | None = None,
    title: str | None = None,
) -> SectionSplitResult:
    """Split only on explicit headings and preserve all other source text."""
    normalized_content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    resolved_title = title.strip() if title and title.strip() else _title_from_content(normalized_content)
    if not normalized_content:
        return SectionSplitResult(source, source_post_id, raw_post_id, resolved_title, 0, [], ["empty_content"])

    lines = normalized_content.split("\n")
    boundaries: list[tuple[int, str, SplitReason, str | None]] = []
    for line_index, line in enumerate(lines, start=1):
        heading = _heading_for_line(line)
        if heading is not None:
            name, reason, inline_text = heading
            boundaries.append((line_index, name, reason, inline_text))

    if not boundaries:
        section = _make_section(
            section_index=1,
            heading=None,
            text=normalized_content,
            start_line=1,
            end_line=len(lines),
            split_reason="whole_notice",
        )
        return SectionSplitResult(source, source_post_id, raw_post_id, resolved_title, 1, [section], ["no_explicit_section_heading"])

    sections: list[NoticeSection] = []
    first_boundary_line = boundaries[0][0]
    if first_boundary_line > 1:
        preamble = "\n".join(lines[: first_boundary_line - 1]).strip()
        if _has_substantive_preamble(preamble):
            sections.append(_make_section(
                section_index=len(sections) + 1,
                heading=None,
                text=preamble,
                start_line=1,
                end_line=first_boundary_line - 1,
                split_reason="whole_notice",
            ))

    for boundary_index, (line_number, heading, reason, inline_text) in enumerate(boundaries):
        next_line = boundaries[boundary_index + 1][0] if boundary_index + 1 < len(boundaries) else len(lines) + 1
        body_lines = lines[line_number: next_line - 1]
        if inline_text:
            body_lines.insert(0, inline_text)
        sections.append(_make_section(
            section_index=len(sections) + 1,
            heading=heading,
            text="\n".join(body_lines).strip(),
            start_line=line_number,
            end_line=next_line - 1,
            split_reason=reason,
        ))

    return SectionSplitResult(source, source_post_id, raw_post_id, resolved_title, len(sections), sections, [])
