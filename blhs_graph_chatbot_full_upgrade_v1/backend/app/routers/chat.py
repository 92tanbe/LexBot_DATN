from __future__ import annotations

from fastapi import APIRouter

from app.models.conversation import LegalChatResponse
from app.models.legal_output import ScenarioAnalysisResponse
from app.models.schemas import AnalyzeScenarioRequest, LegalChatRequest
from app.services.dialogue_manager import handle_legal_chat
from app.services.legal_pipeline import run_legal_analysis

router = APIRouter(tags=["chat"])


@router.post("/analyze-scenario", response_model=ScenarioAnalysisResponse)
def analyze_scenario(req: AnalyzeScenarioRequest) -> ScenarioAnalysisResponse:
    return run_legal_analysis(
        scenario=req.scenario,
        top_k=req.top_k,
        include_debug=req.include_debug,
        answer_style=req.answer_style,
    )


@router.post("/chat/legal", response_model=LegalChatResponse)
def legal_chat(req: LegalChatRequest) -> LegalChatResponse:
    return handle_legal_chat(
        message=req.message,
        case_id=req.case_id,
        case_version=req.case_version,
        answers=req.answers,
        top_k=req.top_k,
        include_debug=req.include_debug,
        answer_style=req.answer_style,
        mode=req.mode,
    )
