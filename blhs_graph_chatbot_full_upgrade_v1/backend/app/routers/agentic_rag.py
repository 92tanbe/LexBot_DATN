from __future__ import annotations

from fastapi import APIRouter

from app.models.agentic import AgenticChatRequest, AgenticChatResponse
from app.services.agentic_rag_service import run_agentic_rag

router = APIRouter(prefix="/api/agentic-rag", tags=["agentic-rag"])


@router.post("/query", response_model=AgenticChatResponse)
def agentic_query(req: AgenticChatRequest) -> AgenticChatResponse:
    return run_agentic_rag(req)
