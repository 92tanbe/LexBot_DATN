from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.conversation import ClarificationAnswer

AgenticModeType = Literal["auto", "fast", "thinking", "agentic"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
    search_type: Literal["hybrid", "fulltext", "graph", "vector"] = "hybrid"
    include_debug: bool = False


class SearchCandidate(BaseModel):
    article_code: str | None = None
    title: str | None = None
    article_title: str | None = None
    article_content: str | None = None
    crime_name: str | None = None
    score: float = 0.0
    source: str | None = None
    sources: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    reason: str | None = None


class FinalAnswer(BaseModel):
    content: str
    format: Literal["text", "markdown"] = "text"
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    candidates: list[SearchCandidate]
    final_answer: FinalAnswer | None = None
    missing_facts: list[str] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    debug: dict | None = None


class AnalyzeScenarioRequest(BaseModel):
    scenario: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=30)
    include_debug: bool = False
    answer_style: Literal["auto", "balanced", "conversational", "brief", "educational", "structured"] = "auto"


class LegalChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str | None = None
    case_version: int | None = Field(default=None, ge=0)
    message: str = ""
    answers: list[ClarificationAnswer] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=30)
    include_debug: bool = False
    answer_style: Literal["auto", "balanced", "conversational", "brief", "educational", "structured"] = "auto"
    mode: AgenticModeType = "auto"

    @model_validator(mode="after")
    def require_message_or_answers(self) -> "LegalChatRequest":
        if not (self.message or "").strip() and not self.answers:
            raise ValueError("message hoặc answers phải có ít nhất một giá trị")
        return self


class NormalizeRequest(BaseModel):
    text: str = Field(min_length=1)
