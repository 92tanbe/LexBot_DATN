from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentMode = Literal["auto", "fast", "thinking", "agentic", "pdf_lookup"]
AgentStatus = Literal["need_more_info", "answered", "candidate", "not_found", "error"]


class AgentAction:
    EXTRACT_FACTS = "EXTRACT_FACTS"
    MERGE_CONVERSATION_FACTS = "MERGE_CONVERSATION_FACTS"
    CHECK_MISSING_INFO = "CHECK_MISSING_INFO"
    ASK_FOLLOW_UP = "ASK_FOLLOW_UP"
    REWRITE_QUERY = "REWRITE_QUERY"
    DECOMPOSE_QUERY = "DECOMPOSE_QUERY"
    RETRIEVE_HYBRID = "RETRIEVE_HYBRID"
    RETRIEVE_GRAPH = "RETRIEVE_GRAPH"
    RETRIEVE_FAST = "RETRIEVE_FAST"
    RERANK_CONTEXT = "RERANK_CONTEXT"
    BUILD_CONTEXT = "BUILD_CONTEXT"
    MATCH_LEGAL_RULES = "MATCH_LEGAL_RULES"
    GENERATE_ANSWER = "GENERATE_ANSWER"
    VALIDATE_ANSWER = "VALIDATE_ANSWER"
    RETURN_FINAL = "RETURN_FINAL"
    RETURN_CANDIDATE = "RETURN_CANDIDATE"
    RETURN_NOT_FOUND = "RETURN_NOT_FOUND"
    RETURN_ERROR_FALLBACK = "RETURN_ERROR_FALLBACK"


class LegalFacts(BaseModel):
    intent: str = "unknown"
    domain: str = "unknown"
    act: str = "unknown"
    substance: str = "unknown"
    quantity: float | None = None
    unit: str | None = None
    normalized_quantity_g: float | None = None
    article_refs: list[str] = Field(default_factory=list)
    raw_text: str = ""


class MissingInfoResult(BaseModel):
    status: Literal["need_more_info", "sufficient"]
    missing_fields: list[str] = Field(default_factory=list)
    question: str | None = None


class RetrievalObservation(BaseModel):
    retrieved_count: int = 0
    graph_context_count: int = 0
    candidate_articles: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class LegalReasoningObservation(BaseModel):
    status: Literal["matched", "candidate", "not_found"]
    matched_article: str | None = None
    matched_crime: str | None = None
    matched_condition: str | None = None
    matched_penalty_frame: str | None = None
    reasoning_steps: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    candidate_frames: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str = "low"


class AgentTraceStep(BaseModel):
    step: int
    action: str
    tool: str
    result: Any


class ConversationState(BaseModel):
    conversation_id: str
    facts: LegalFacts = Field(default_factory=LegalFacts)
    raw_messages: list[str] = Field(default_factory=list)
    last_question: str | None = None


class AgenticChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    mode: AgentMode = "auto"
    include_debug: bool = False
    top_k: int = Field(default=8, ge=1, le=30)


class AgenticChatResponse(BaseModel):
    status: AgentStatus
    answer: str
    conversation_id: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    reasoning: dict[str, Any] | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    candidate_frames: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str = "low"
    agent_trace: list[AgentTraceStep] | None = None
    debug: dict[str, Any] | None = None
