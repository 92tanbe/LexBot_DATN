"""Schema Pydantic cho lưu trữ và đọc lịch sử chat (MongoDB + API)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

QueryModeType = Literal["fast", "thinking"]
ChatModeType = Literal["tra_cuu_pdf", "phan_tich"]
ChatbotProviderType = Literal["rag_v1", "graph_v2"]


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
        description="rag_v1 = LexBot RAG (/rag/query); graph_v2 = BLHS Graph (/analyze-scenario).",
    )
    conversation_id: str | None = Field(
        default=None,
        max_length=128,
        description="ID phiên hội thoại do client tạo (ví dụ UUID) để nhóm các lượt chat.",
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
