"""Pydantic schema cho API va retrieval pipeline.

Cac schema chinh:
- ChatRequest / ChatResponse: API endpoint
- RetrievedChunk: 1 chunk lay ra tu vector / fulltext / graph
- Citation: trich dan cu the (rule_id, dieu, khoan)
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# -------------------------- Retrieval primitives ----------------------------

ChunkLevel = Literal["dieu", "khoan", "graph"]
ChunkSource = Literal["vector", "fulltext", "graph", "rrf", "rerank"]


class RetrievedChunk(BaseModel):
    """1 ket qua retrieval truoc/sau rerank."""

    source: ChunkSource
    level: ChunkLevel
    text: str
    score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float | None = None

    # Provenance
    article: int | None = None
    clause: int | None = None
    rule_id: str | None = None
    crime_id: str | None = None
    dieu_name: str | None = None
    chuong: str | None = None
    nhom_toi: str | None = None
    logic: str | None = None

    # Extra meta
    meta: dict = Field(default_factory=dict)

    def merge_provenance(self, other: "RetrievedChunk") -> None:
        """Bo sung provenance neu thieu."""
        for field in ("article", "clause", "rule_id", "crime_id", "dieu_name", "chuong", "nhom_toi", "logic"):
            if getattr(self, field) is None and getattr(other, field) is not None:
                setattr(self, field, getattr(other, field))


# ----------------------------- Citations ------------------------------------


class Citation(BaseModel):
    """Trich dan can ban phap ly."""

    article: int
    clause: int | None = None
    rule_id: str | None = None
    ten_toi: str | None = None
    snippet: str | None = None


# ---------------------------- API request/response --------------------------

ChatMode = Literal[
    "phan_tich",
    "tra_cuu_pdf",
]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=30)
    chat_mode: ChatMode = Field(
        default="tra_cuu_pdf",
        description=(
            "tra_cuu_pdf (mac dinh): tra loi/chat nhanh + trich theo VB hop nhat trong file PDF (dataset). "
            "phan_tich: bat pipeline RAG/Neo4j + LLM de phan tich tinh huong."
        ),
    )
    include_debug: bool = Field(
        default=False,
        description="Tra ve them debug info (entities, retrieval, rerank)",
    )


class StageEvent(BaseModel):
    """1 su kien streaming SSE."""

    stage: str  # stage1_done (hieu query), stage2_done (retrieval), ...
    payload: dict = Field(default_factory=dict)


class ChatResponseDebug(BaseModel):
    entities: dict | None = None
    sub_queries: list[str] = Field(default_factory=list)
    rewritten_queries: list[str] = Field(default_factory=list)
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    reranked: list[RetrievedChunk] = Field(default_factory=list)
    cypher_used: list[str] = Field(default_factory=list)
    timings_ms: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    question: str
    final_answer: str
    structured: dict  # CaseAnalysis se ghi vao day
    citations: list[Citation] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    debug: Optional[ChatResponseDebug] = None
