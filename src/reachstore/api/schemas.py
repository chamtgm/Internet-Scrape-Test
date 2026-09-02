from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SourceStatusOut(BaseModel):
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
