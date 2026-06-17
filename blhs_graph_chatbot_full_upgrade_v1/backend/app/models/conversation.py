from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.facts import ExtractedFacts
from app.models.legal_output import CandidateArticle, LegalReasoningItem


class CaseStatus(str, Enum):
    collecting_facts = "collecting_facts"
    ready_to_answer = "ready_to_answer"
    answered = "answered"
    insufficient_information = "insufficient_information"


class MissingFactItem(BaseModel):
    key: str
    label: str
    description: str
    critical: bool = False
    domain: str | None = None
    question: str | None = None


ClarificationInputType = Literal[
    "single_choice",
    "multi_choice",
    "number",
    "text",
    "date",
    "boolean",
    "actor_matrix",
]


class ClarificationOption(BaseModel):
    id: str
    label: str
    requires_value: bool = False
    value_type: Literal["text", "number", "date"] | None = None
    placeholder: str | None = None


class ClarificationQuestion(BaseModel):
    id: str
    fact_path: str
    group: str
    text: str
    input_type: ClarificationInputType
    options: list[ClarificationOption] = Field(default_factory=list)
    required: bool = False
    critical: bool = False
    allow_free_text: bool = False
    unit: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    reason: str
    affected_articles: list[str] = Field(default_factory=list)
    actor_id: str | None = None
    depends_on_question_id: str | None = None
    depends_on_option_ids: list[str] = Field(default_factory=list)


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    selected_option_ids: list[str] = Field(default_factory=list)
    value: Any | None = None
    free_text: str | None = None


class ClarificationForm(BaseModel):
    type: Literal["form"] = "form"
    question_set_id: str
    can_submit_partial: bool = True
    questions: list[ClarificationQuestion] = Field(default_factory=list)


class FactPatch(BaseModel):
    path: str
    value: Any | None = None
    source: Literal["clarification_answer", "message", "system"] = "clarification_answer"
    evidence_source: str | None = None
    confidence: float = 0.8
    merge_strategy: Literal["set", "append", "set_if_higher_confidence"] = "set_if_higher_confidence"


class IssuedQuestionSet(BaseModel):
    question_set_id: str
    case_id: str
    case_version: int
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    option_patches: dict[str, dict[str, list[FactPatch]]] = Field(default_factory=dict)
    value_patches: dict[str, list[FactPatch]] = Field(default_factory=dict)
    issued_at: datetime = Field(default_factory=datetime.utcnow)


class ProvisionalFinding(BaseModel):
    status: Literal[
        "possible_hypothesis",
        "provisional_finding",
        "insufficient_evidence",
        "supported_conclusion",
    ]
    text: str
    affected_articles: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class ConversationTurn(BaseModel):
    user_message: str
    extracted_facts: ExtractedFacts
    answers: list[ClarificationAnswer] = Field(default_factory=list)
    bot_response_summary: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CollectedFacts(BaseModel):
    facts: ExtractedFacts = Field(default_factory=ExtractedFacts)


class DialogueState(BaseModel):
    status: CaseStatus = CaseStatus.collecting_facts
    collected_facts: CollectedFacts = Field(default_factory=CollectedFacts)
    missing_facts: list[MissingFactItem] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CaseSession(BaseModel):
    case_id: str
    version: int = 0
    status: CaseStatus = CaseStatus.collecting_facts
    facts: ExtractedFacts = Field(default_factory=ExtractedFacts)
    scenario_text: str = ""
    turns: list[ConversationTurn] = Field(default_factory=list)
    issued_question_sets: list[IssuedQuestionSet] = Field(default_factory=list)
    answered_question_ids: list[str] = Field(default_factory=list)
    answered_unknown_question_ids: list[str] = Field(default_factory=list)
    candidate_hypotheses: list[ProvisionalFinding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LegalChatResponse(BaseModel):
    case_id: str
    case_version: int = 0
    status: CaseStatus
    facts: ExtractedFacts
    provisional_findings: list[ProvisionalFinding] = Field(default_factory=list)
    missing_facts: list[MissingFactItem] = Field(default_factory=list)
    clarification: ClarificationForm | None = None
    clarifying_questions: list[str] = Field(default_factory=list)
    candidate_articles: list[CandidateArticle] = Field(default_factory=list)
    legal_reasoning: list[LegalReasoningItem] = Field(default_factory=list)
    final_answer: str
    confidence: float = 0.0
    citations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    debug: dict[str, Any] | None = None
