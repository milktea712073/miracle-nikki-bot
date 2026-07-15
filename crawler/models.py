"""Crawler data models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Post:
    """Raw data extracted from an external announcement source."""

    post_id: str
    url: str
    content: str
    published_at: datetime | None
    images: list[str]
    source: str = "facebook"
    metadata: Mapping[str, object] | None = None
