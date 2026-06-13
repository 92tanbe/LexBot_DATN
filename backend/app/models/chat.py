"""Schema Pydantic cho lưu trữ và đọc lịch sử chat (MongoDB + API)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QueryModeType = Literal["fast", "thinking"]
ChatModeType = Literal["tra_cuu_pdf", "phan_tich"]
ChatbotProviderType = Literal["rag_v1", "graph_v2"]
AnswerStyleType = Literal["auto", "balanced", "conversational", "brief", "educational", "structured"]
AgenticModeType = Literal["auto", "fast", "thinking", "agentic"]
ClarificationInputType = Literal[
    "single_choice",
    "multi_choice",
    "number",
    "text",
    "date",
    "boolean",
    "actor_matrix",
]
CaseStatusType = Literal[
    "collecting_facts",
    "ready_to_answer",
    "answered",
    "insufficient_information",
]


class ChatQueryRequest(BaseModel):
    """Body POST /chat/query: forward sang microservice chatbot + metadata lịch sử."""

    question: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=30)
    query_mode: QueryModeType = Field(
        default="fast",
        description="fast hoặc thinking — forward sang chatbot.",
    )
    chat_mode: ChatModeType | None = Field(
        default=None,
        description="tra_cuu_pdf / phan_tich hoặc None.",
    )
    chatbot_provider: ChatbotProviderType = Field(
        default="rag_v1",
        description="rag_v1 = LexBot RAG (/rag/query); graph_v2 = Agentic Graph RAG.",
    )
    conversation_id: str | None = Field(
        default=None,
        max_length=128,
        description="ID phiên hội thoại do client tạo (ví dụ UUID) để nhóm các lượt chat.",
    )
    mode: AgenticModeType | None = Field(
        default=None,
        description="Mode Agentic Graph RAG khi chatbot_provider=graph_v2.",
    )


class ChatProviderInfo(BaseModel):
    """Một microservice chatbot có thể chọn trên UI."""

    id: ChatbotProviderType
    name: str
    description: str
    base_url: str = ""
    enabled: bool = True
    modes: list[str] = Field(default_factory=list)
    neo4j_uri_hint: str = Field(
        default="",
        description="Hostname Aura (metadata — cấu hình thật nằm trên từng microservice).",
    )
    neo4j_database: str = Field(
        default="neo4j",
        description="Tên database Neo4j riêng của provider này.",
    )


class ChatProvidersResponse(BaseModel):
    """GET /chat/providers — danh sách server chatbot khả dụng."""

    providers: list[ChatProviderInfo]
    default_provider: ChatbotProviderType = "rag_v1"


class MissingFactItem(BaseModel):
    """Một dữ kiện còn thiếu trong flow pháp luật nhiều lượt."""

    key: str = ""
    label: str = ""
    description: str = ""
    critical: bool = False
    domain: str | None = None
    question: str | None = None


class ClarificationAnswer(BaseModel):
    """Một câu trả lời form làm rõ gửi sang AI backend.

    Chỉ cho phép các field trong contract; không nhận fact_path/fact patch từ client.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(..., min_length=1, max_length=256)
    selected_option_ids: list[str] = Field(default_factory=list)
    value: Any | None = None
    free_text: str | None = Field(default=None, max_length=2000)


class ClarificationOption(BaseModel):
    id: str = ""
    label: str = ""
    requires_value: bool = False
    value_type: Literal["text", "number", "date"] | None = None
    placeholder: str | None = None


class ClarificationQuestion(BaseModel):
    id: str = ""
    fact_path: str = ""
    group: str = ""
    text: str = ""
    input_type: ClarificationInputType = "text"
    options: list[ClarificationOption | dict[str, Any]] = Field(default_factory=list)
    required: bool = False
    critical: bool = False
    allow_free_text: bool = False
    unit: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    reason: str = ""
    affected_articles: list[str] = Field(default_factory=list)
    actor_id: str | None = None
    depends_on_question_id: str | None = None
    depends_on_option_ids: list[str] = Field(default_factory=list)


class ClarificationForm(BaseModel):
    type: Literal["form"] = "form"
    question_set_id: str = ""
    can_submit_partial: bool = True
    questions: list[ClarificationQuestion | dict[str, Any]] = Field(default_factory=list)


class LegalChatRequest(BaseModel):
    """Body POST /chat/legal: proxy tới AI backend Graph RAG nhiều lượt."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(default="", max_length=8000)
    case_id: str | None = Field(default=None, max_length=128)
    case_version: int | None = Field(default=None, ge=0)
    answers: list[ClarificationAnswer] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=30)
    include_debug: bool = False
    answer_style: AnswerStyleType = "auto"
    mode: AgenticModeType = "auto"

    @model_validator(mode="after")
    def require_message_or_answers(self) -> "LegalChatRequest":
        if not (self.message or "").strip() and not self.answers:
            raise ValueError("message hoặc answers phải có ít nhất một giá trị")
        return self


class LegalChatResponse(BaseModel):
    """Response POST /chat/legal đã normalize từ AI backend Graph RAG."""

    case_id: str
    case_version: int = 0
    status: CaseStatusType
    facts: dict[str, Any] = Field(default_factory=dict)
    provisional_findings: list[dict[str, Any]] = Field(default_factory=list)
    missing_facts: list[MissingFactItem | dict[str, Any] | str] = Field(default_factory=list)
    clarification: ClarificationForm | dict[str, Any] | None = None
    clarifying_questions: list[str] = Field(default_factory=list)
    candidate_articles: list[dict[str, Any]] = Field(default_factory=list)
    legal_reasoning: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str = ""
    confidence: float = 0.0
    citations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    debug: dict[str, Any] | None = None
    possible_penalty_frames: list[dict[str, Any]] = Field(default_factory=list)
    chatbot_provider: ChatbotProviderType = "graph_v2"
    graph_mode: str = "agentic"


class ChatHistoryItem(BaseModel):
    """Một mục trong danh sách lịch sử (không chứa toàn bộ response JSON)."""

    id: str
    user_id: str
    question: str
    preview_answer: str = Field(..., description="Rút gọn final_answer cho danh sách")
    query_mode: QueryModeType = "fast"
    chat_mode: ChatModeType | None = None
    chatbot_provider: ChatbotProviderType = "rag_v1"
    conversation_id: str | None = None
    created_at: datetime

    @field_validator("query_mode", mode="before")
    @classmethod
    def _coerce_query_mode(cls, v: Any) -> str:
        if v in ("fast", "thinking"):
            return v
        return "fast"

    @field_validator("chat_mode", mode="before")
    @classmethod
    def _coerce_chat_mode(cls, v: Any) -> str | None:
        if v is None or v == "":
            return None
        if v in ("tra_cuu_pdf", "phan_tich"):
            return v
        return None

    @field_validator("chatbot_provider", mode="before")
    @classmethod
    def _coerce_provider(cls, v: Any) -> str:
        if v in ("rag_v1", "graph_v2"):
            return v
        if v in ("rag", "graph"):
            return "graph_v2" if v == "graph" else "rag_v1"
        return "rag_v1"


class ChatHistoryDetail(BaseModel):
    """Chi tiết một lượt chat — đủ dữ liệu để frontend render lại."""

    id: str
    user_id: str
    question: str
    query_mode: QueryModeType = "fast"
    chat_mode: ChatModeType | None = None
    chatbot_provider: ChatbotProviderType = "rag_v1"
    conversation_id: str | None = None
    created_at: datetime
    response: dict[str, Any] = Field(default_factory=dict)

    @field_validator("query_mode", mode="before")
    @classmethod
    def _coerce_query_mode(cls, v: Any) -> str:
        if v in ("fast", "thinking"):
            return v
        return "fast"

    @field_validator("chat_mode", mode="before")
    @classmethod
    def _coerce_chat_mode(cls, v: Any) -> str | None:
        if v is None or v == "":
            return None
        if v in ("tra_cuu_pdf", "phan_tich"):
            return v
        return None

    @field_validator("chatbot_provider", mode="before")
    @classmethod
    def _coerce_provider(cls, v: Any) -> str:
        if v in ("rag_v1", "graph_v2"):
            return v
        if v in ("rag", "graph"):
            return "graph_v2" if v == "graph" else "rag_v1"
        return "rag_v1"


class ChatHistoryListResponse(BaseModel):
    """GET /chat/history — danh sách có phân trang."""

    items: list[ChatHistoryItem]
    total: int
    skip: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
