"""Crawler data models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Post:
    """Raw data extracted from one Facebook post."""

    post_id: str
    url: str
    content: str
    published_at: datetime | None
    images: list[str]
