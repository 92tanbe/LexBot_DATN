from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.facts import ExtractedFacts


class CandidateArticle(BaseModel):
    article_code: str
    title: str
    crime_name: str | None = None
    score: float = 0.0
    source: str = ""
    matched_terms: list[str] = Field(default_factory=list)
    reason: str | None = None


class LegalContext(BaseModel):
    article: dict[str, Any]
    crime: dict[str, Any] | None = None
    clauses: list[dict[str, Any]] = Field(default_factory=list)
    points: list[dict[str, Any]] = Field(default_factory=list)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    penalty_frames: list[dict[str, Any]] = Field(default_factory=list)
    penalties: list[dict[str, Any]] = Field(default_factory=list)
    act_requirements: list[dict[str, Any]] = Field(default_factory=list)
    subject_requirements: list[dict[str, Any]] = Field(default_factory=list)
    object_requirements: list[dict[str, Any]] = Field(default_factory=list)
    consequence_requirements: list[dict[str, Any]] = Field(default_factory=list)
    quantity_thresholds: list[dict[str, Any]] = Field(default_factory=list)
    exceptions: list[dict[str, Any]] = Field(default_factory=list)
    mitigating_factors: list[dict[str, Any]] = Field(default_factory=list)
    aggravating_factors: list[dict[str, Any]] = Field(default_factory=list)
    references: list[dict[str, Any]] = Field(default_factory=list)


class MatchedElement(BaseModel):
    type: str
    node_id: str | None = None
    text: str
    score: float = 0.0
    reason: str


class LegalReasoningItem(BaseModel):
    article_code: str
    title: str
    crime_name: str | None = None
    classification: str
    finding_status: Literal[
        "possible_hypothesis",
        "provisional_finding",
        "insufficient_evidence",
        "supported_conclusion",
    ] = "possible_hypothesis"
    why_relevant: str
    matched_elements: list[MatchedElement] = Field(default_factory=list)
    missing_elements: list[str] = Field(default_factory=list)
    possible_penalty_frames: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class ScenarioAnalysisResponse(BaseModel):
    facts: ExtractedFacts
    normalized_signals: list[dict[str, Any]] = Field(default_factory=list)
    candidate_articles: list[CandidateArticle] = Field(default_factory=list)
    legal_contexts: list[LegalContext] = Field(default_factory=list)
    matched_conditions: list[MatchedElement] = Field(default_factory=list)
    possible_penalty_frames: list[dict[str, Any]] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    legal_reasoning: list[LegalReasoningItem] = Field(default_factory=list)
    final_answer: str
    confidence: float = 0.0
    citations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    debug: dict[str, Any] | None = None
