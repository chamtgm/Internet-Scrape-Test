from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NormalizedItem:
    """Platform-agnostic item. Every adapter emits exactly this shape."""

    external_id: str
    url: str
    content_text: str
    title: str | None = None
    author_handle: str | None = None
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)
