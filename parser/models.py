"""Models for parser output before human review."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SuitCandidate:
    """A possible suit name extracted from an announcement."""

    name: str
    confidence: float
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class ParseDraft:
    """Rule-based extraction result for one raw post."""

    title: str | None
    event_name_candidate: str | None
    official_series_candidate: str | None
    period_type_candidate: str
    start_at_candidate: str | None
    end_at_candidate: str | None
    player_category_candidate: str | None
    acquisition_method_candidate: str | None
    confidence: float
    parser_notes: str | None
    suits: list[SuitCandidate] = field(default_factory=list)
    content_type_candidate: str = "other"
