from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reachstore import query
from reachstore.api.deps import get_session
from reachstore.api.schemas import SourcesResponse, SourceStatusOut

router = APIRouter(prefix="/api")


@router.get("/sources", response_model=SourcesResponse)
def list_sources(session: Session = Depends(get_session)) -> SourcesResponse:
    statuses = query.source_health(session)
    return SourcesResponse(sources=[SourceStatusOut(**vars(s)) for s in statuses])
