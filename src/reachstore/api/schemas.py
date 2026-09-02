from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SourceStatusOut(BaseModel):
    """Mirrors query.SourceStatus exactly; built via SourceStatusOut(**vars(s)).

    extra="forbid" makes that guarantee real in both directions: pydantic's
    default (extra="ignore") already raises when a field is missing, but
    silently drops any field added to the dataclass with no counterpart here.
    Scoped to this model only -- it is the sole one built by keyword-splatting
    a dataclass; the others are constructed with explicit keyword arguments.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: int
    kind: str
    identifier: str
    last_status: str | None
    last_run_at: datetime | None
    consecutive_failures: int
    needs_attention: bool
    error_text: str | None
    item_count: int


class SourcesResponse(BaseModel):
    sources: list[SourceStatusOut]


class ItemSummary(BaseModel):
    id: int
    title: str | None
    url: str
    author_handle: str | None
    published_at: datetime | None
    source_id: int
    source_kind: str
    source_identifier: str
    excerpt: str


class ItemDetail(ItemSummary):
    content_text: str
    fetched_at: datetime


class Cursor(BaseModel):
    published_at: datetime | None
    id: int


class FeedResponse(BaseModel):
    items: list[ItemSummary]
    next_cursor: Cursor | None


class SearchResponse(BaseModel):
    items: list[ItemSummary]
