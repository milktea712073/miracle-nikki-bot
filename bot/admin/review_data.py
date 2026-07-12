"""Service helpers that compose existing review and import-layer APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from database.knowledge_repository import KnowledgeRepository
from database.review_repository import ReviewRepository


STATUS_LABELS = {
    "auto": "自動建立，尚未確認",
    "needs_review": "待補資料／待校正",
    "pending": "待審核",
    "reviewed": "已審核",
    "approved": "已確認",
    "rejected": "已拒絕",
    "ignored": "已忽略",
}
PERIOD_TYPE_LABELS = {
    "debut": "首次",
    "rerun": "復刻",
    "wish_gate": "心之門",
    "return": "復出",
    "unknown": "未分類",
}


@dataclass(frozen=True, slots=True)
class DraftReviewData:
    """Parser output and editable review data for one draft."""

    draft: dict[str, object]
    review: dict[str, object]
    event_type_name: str | None
    acquisition_method_name: str | None


def get_draft_review_data(draft_id: int) -> DraftReviewData:
    """Load a parse draft and its existing human-review record."""
    knowledge_repository = KnowledgeRepository()
    connection = knowledge_repository.connect()
    try:
        draft = knowledge_repository.get_parse_draft(connection, draft_id)
    finally:
        connection.close()
    if draft is None:
        raise ValueError(f"找不到草稿 #{draft_id}。")

    review_repository = ReviewRepository()
    review = review_repository.get_or_create_review(draft_id)
    event_type_name = _option_name(
        review_repository.get_reference_options("event_types"), review["event_type_id"]
    )
    acquisition_method_name = _option_name(
        review_repository.get_reference_options("acquisition_methods"),
        review["acquisition_method_id"],
    )
    return DraftReviewData(draft, review, event_type_name, acquisition_method_name)


def list_pending_drafts(limit: int = 10) -> list[DraftReviewData]:
    """Load a small, display-ready batch of pending review drafts."""
    repository = ReviewRepository()
    return [
        get_draft_review_data(int(item["id"]))
        for item in repository.list_pending_reviews(limit)
    ]


def _option_name(options: list[tuple[int, str]], option_id: object) -> str | None:
    for candidate_id, name in options:
        if candidate_id == option_id:
            return name
    return None


def format_period(start_at: object, end_at: object) -> str:
    """Render candidate ISO timestamps in a concise Taiwan-facing format."""
    if not start_at and not end_at:
        return "未提供"
    start_text = _format_datetime(start_at)
    end_text = _format_datetime(end_at)
    return f"{start_text} ～ {end_text}"


def _format_datetime(value: object) -> str:
    if not value:
        return "未提供"
    raw_value = str(value)
    try:
        parsed = datetime.fromisoformat(raw_value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo("Asia/Taipei"))
        return parsed.strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return raw_value.replace("T", " ").split("+")[0]
