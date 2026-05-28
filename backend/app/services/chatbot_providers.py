"""Adapter gọi nhiều microservice chatbot — mỗi provider có endpoint và schema riêng.

- rag_v1: service DATN gốc — POST /rag/query (question, query_mode, chat_mode)
- graph_v2: BLHS Graph Chatbot v2 — POST /search hoặc /analyze-scenario (scenario/query)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from app.models.chat import ChatQueryRequest

logger = logging.getLogger(__name__)

ChatbotProviderId = Literal["rag_v1", "graph_v2"]

DEFAULT_RAG_V1_URL = "http://127.0.0.1:8001"
DEFAULT_GRAPH_V2_URL = "https://lexbot-production-bb10.up.railway.app"


def _uri_host_hint(raw: str) -> str:
    """Trích hostname từ URI Neo4j — chỉ dùng hiển thị, không lộ credential."""
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        parsed = urlparse(value)
        return parsed.hostname or value.split("://", 1)[-1].split("/")[0].split("@")[-1]
    except Exception:
        return value[:48]


def _provider_neo4j_meta(provider_id: ChatbotProviderId) -> tuple[str, str]:
    """Metadata Neo4j theo provider — mỗi microservice dùng Aura instance riêng."""
    if provider_id == "graph_v2":
        uri = os.getenv("NEO4J_GRAPH_V2_URI") or os.getenv("NEO4J_GRAPH_V2_URI_HINT", "")
        database = (os.getenv("NEO4J_GRAPH_V2_DATABASE") or "neo4j").strip() or "neo4j"
        return _uri_host_hint(uri), database
    uri = os.getenv("NEO4J_RAG_V1_URI") or os.getenv("NEO4J_RAG_V1_URI_HINT", "")
    database = (os.getenv("NEO4J_RAG_V1_DATABASE") or "neo4j").strip() or "neo4j"
    return _uri_host_hint(uri), database


def _normalize_base_url(raw: str, default: str) -> str:
    """Chuẩn hóa base URL — thêm https:// nếu thiếu scheme."""
    value = (raw or "").strip() or default
    lowered = value.lower()
    if not lowered.startswith(("http://", "https://")):
        stub = value.lstrip("/")
        if "localhost" in stub.lower() or "127.0.0.1" in stub:
            value = f"http://{stub}"
        else:
            value = f"https://{stub}"
    return value.rstrip("/")


def _resolve_rag_v1_query_url(base: str) -> str:
    """Nối /rag/query nếu env chỉ có base URL."""
    base = base.rstrip("/")
    path = (urlparse(base).path or "").rstrip("/")
    if not path:
        return f"{base}/rag/query"
    if path.endswith("/rag"):
        return f"{base}/query"
    if path.endswith("/rag/query"):
        return base
    return base


@dataclass(frozen=True)
class ProviderInfo:
    id: ChatbotProviderId
    name: str
    description: str
    base_url: str
    enabled: bool
    modes: list[str]
    neo4j_uri_hint: str = ""
    neo4j_database: str = "neo4j"


def _float_confidence_to_label(value: Any) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "medium"
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _normalize_citations(raw: list[Any] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        article = item.get("article") or item.get("article_code")
        title = item.get("title") or item.get("ten_toi") or ""
        entry: dict[str, Any] = {"title": str(title)}
        if article is not None:
            entry["article"] = article
            entry["article_code"] = str(article)
        if item.get("clause") is not None:
            entry["clause"] = item["clause"]
        if item.get("rule_id"):
            entry["rule_id"] = item["rule_id"]
        if item.get("snippet"):
            entry["snippet"] = item["snippet"]
        items.append(entry)
    return items


def _normalize_graph_v2_search(data: dict[str, Any], question: str) -> dict[str, Any]:
    return {
        "question": question,
        "final_answer": str(data.get("final_answer") or ""),
        "citations": _normalize_citations(data.get("citations")),
        "missing_facts": list(data.get("missing_facts") or []),
        "candidates": list(data.get("candidates") or []),
        "confidence": "medium",
        "chatbot_provider": "graph_v2",
        "graph_mode": "search",
    }


def _normalize_graph_v2_analyze(data: dict[str, Any], question: str) -> dict[str, Any]:
    facts = data.get("facts")
    if hasattr(facts, "model_dump"):
        facts = facts.model_dump()
    elif not isinstance(facts, dict):
        facts = {}

    reasoning_raw = data.get("legal_reasoning") or []
    legal_reasoning: list[dict[str, Any]] = []
    for item in reasoning_raw:
        if hasattr(item, "model_dump"):
            legal_reasoning.append(item.model_dump())
        elif isinstance(item, dict):
            legal_reasoning.append(item)

    candidates_raw = data.get("candidate_articles") or []
    candidate_articles: list[dict[str, Any]] = []
    for item in candidates_raw:
        if hasattr(item, "model_dump"):
            candidate_articles.append(item.model_dump())
        elif isinstance(item, dict):
            candidate_articles.append(item)

    return {
        "question": question,
        "final_answer": str(data.get("final_answer") or ""),
        "citations": _normalize_citations(data.get("citations")),
        "missing_facts": list(data.get("missing_facts") or []),
        "clarifying_questions": list(data.get("clarifying_questions") or []),
        "legal_reasoning": legal_reasoning,
        "facts": facts,
        "candidate_articles": candidate_articles,
        "matched_conditions": list(data.get("matched_conditions") or []),
        "possible_penalty_frames": list(data.get("possible_penalty_frames") or []),
        "warnings": list(data.get("warnings") or []),
        "confidence": _float_confidence_to_label(data.get("confidence")),
        "chatbot_provider": "graph_v2",
        "graph_mode": "analyze",
    }


class ChatbotProviderRegistry:
    """Đăng ký và route request tới đúng microservice chatbot."""

    def __init__(self) -> None:
        rag_base = _normalize_base_url(
            os.getenv("CHATBOT_SERVICE_URL", DEFAULT_RAG_V1_URL),
            DEFAULT_RAG_V1_URL,
        )
        graph_base = _normalize_base_url(
            os.getenv("CHATBOT_GRAPH_V2_URL", DEFAULT_GRAPH_V2_URL),
            DEFAULT_GRAPH_V2_URL,
        )
        self._rag_v1_query_url = _resolve_rag_v1_query_url(rag_base)
        self._rag_v1_base = rag_base
        self._graph_v2_base = graph_base
        self._timeout = float(os.getenv("CHATBOT_TIMEOUT_SECONDS", "120"))
        self._connect_timeout = float(
            os.getenv("CHATBOT_CONNECT_TIMEOUT_SECONDS", "45")
        )

    @property
    def timeout(self) -> httpx.Timeout:
        connect_cap = min(self._connect_timeout, self._timeout)
        return httpx.Timeout(self._timeout, connect=connect_cap)

    def list_providers(self) -> list[ProviderInfo]:
        rag_neo4j_hint, rag_neo4j_db = _provider_neo4j_meta("rag_v1")
        graph_neo4j_hint, graph_neo4j_db = _provider_neo4j_meta("graph_v2")
        rag_desc = "Pipeline RAG gốc — Neo4j Aura riêng + embedding + PDF VB hợp nhất"
        if rag_neo4j_hint:
            rag_desc += f" · DB `{rag_neo4j_db}` @ {rag_neo4j_hint}"
        graph_desc = "Phân tích tình huống graph-first trên Railway — Neo4j Aura riêng"
        if graph_neo4j_hint:
            graph_desc += f" · DB `{graph_neo4j_db}` @ {graph_neo4j_hint}"
        return [
            ProviderInfo(
                id="rag_v1",
                name="LexBot RAG v1",
                description=rag_desc,
                base_url=self._rag_v1_base,
                enabled=True,
                modes=["pdf", "fast", "thinking"],
                neo4j_uri_hint=rag_neo4j_hint,
                neo4j_database=rag_neo4j_db,
            ),
            ProviderInfo(
                id="graph_v2",
                name="BLHS Graph v2",
                description=graph_desc,
                base_url=self._graph_v2_base,
                enabled=True,
                modes=["fast", "thinking"],
                neo4j_uri_hint=graph_neo4j_hint,
                neo4j_database=graph_neo4j_db,
            ),
        ]

    def get_provider(self, provider_id: str) -> ProviderInfo:
        for item in self.list_providers():
            if item.id == provider_id:
                return item
        raise ValueError(f"Chatbot provider không hợp lệ: {provider_id}")

    async def forward(self, request: ChatQueryRequest) -> dict[str, Any]:
        provider_id = request.chatbot_provider or "rag_v1"
        if provider_id == "graph_v2":
            return await self._forward_graph_v2(request)
        return await self._forward_rag_v1(request)

    async def _forward_rag_v1(self, request: ChatQueryRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question": request.question,
            "top_k": request.top_k,
            "query_mode": request.query_mode,
        }
        if request.chat_mode is not None:
            payload["chat_mode"] = request.chat_mode

        logger.info(
            "chatbot rag_v1: POST %s query_mode=%s chat_mode=%s",
            self._rag_v1_query_url,
            request.query_mode,
            request.chat_mode,
        )
        data = await self._post_json(self._rag_v1_query_url, payload)
        if isinstance(data, dict):
            data.setdefault("chatbot_provider", "rag_v1")
        return data

    async def _forward_graph_v2(self, request: ChatQueryRequest) -> dict[str, Any]:
        # graph_v2 không có chat_mode PDF — map sang search hoặc analyze-scenario
        use_analyze = (
            request.chat_mode == "phan_tich"
            or request.query_mode == "thinking"
        )

        if use_analyze:
            url = f"{self._graph_v2_base}/analyze-scenario"
            payload = {
                "scenario": request.question,
                "top_k": request.top_k,
                "include_debug": False,
            }
            logger.info("chatbot graph_v2: POST %s (analyze-scenario)", url)
            data = await self._post_json(url, payload)
            return _normalize_graph_v2_analyze(data, request.question)

        url = f"{self._graph_v2_base}/search"
        payload = {
            "query": request.question,
            "top_k": request.top_k,
            "search_type": "hybrid",
            "include_debug": False,
        }
        logger.info("chatbot graph_v2: POST %s (search)", url)
        data = await self._post_json(url, payload)
        return _normalize_graph_v2_search(data, request.question)

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                error_detail = response.text[:2000] if response.text else ""
                try:
                    err_json = response.json()
                    error_detail = str(err_json.get("detail", err_json))[:2000]
                except Exception:
                    pass
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}: {error_detail}",
                    request=response.request,
                    response=response,
                )
            return response.json()


registry = ChatbotProviderRegistry()
