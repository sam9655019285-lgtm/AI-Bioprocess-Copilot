"""Finding precedents endpoint (Phase 18). Read-only and deterministic; nothing is stored, Gemini is not called."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from .db import get_session
from .precedents import PrecedentQuery, PrecedentResult, find_precedents

router = APIRouter(prefix="/api/precedents", tags=["precedents"])


@router.post("/search", response_model=PrecedentResult)
def search(query: PrecedentQuery, session: Session = Depends(get_session)):
    """Exact same-rule matches in stored experiments and what the stored data showed afterwards."""
    return find_precedents(session, query)
