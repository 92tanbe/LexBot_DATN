"""Adapter gọi nhiều microservice chatbot — mỗi provider có endpoint và schema riêng.

- rag_v1: service DATN gốc — POST /rag/query (question, query_mode, chat_mode)
- graph_v2: BLHS Graph RAG — POST /chat/legal cho hội thoại pháp luật nhiều lượt
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from app.models.chat import ChatQueryRequest, LegalChatRequest

logger = logging.getLogger(__name__)

ChatbotProviderId = Literal["rag_v1", "graph_v2"]

DEFAULT_RAG_V1_URL = "http://127.0.0.1:8001"
DEFAULT_GRAPH_V2_URL = ""

AGENTIC_STATUS_MAP = {
    "need_more_info": "collecting_facts",
    "answered": "answered",
    "candidate": "answered",
    "not_found": "insufficient_information",
    "error": "insufficient_information",
}

AGENTIC_CONFIDENCE_MAP = {
    "high": 0.85,
    "medium": 0.65,
    "low": 0.35,
}

MISSING_FIELD_DESCRIPTIONS = {
    "act": "Thiếu hành vi cụ thể",
    "substance": "Thiếu loại chất/tang vật cụ thể",
    "quantity": "Thiếu khối lượng hoặc số lượng cụ thể",
}


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
    if not value:
        return ""
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


def _as_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    return [raw]


def _normalize_citations(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _as_list(raw):
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


def _agentic_confidence_to_float(value: Any) -> float:
    if isinstance(value, str):
        return AGENTIC_CONFIDENCE_MAP.get(value.lower(), 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_agentic_missing_fields(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _as_list(raw):
        if isinstance(item, dict):
            key = str(item.get("key") or item.get("field") or item.get("name") or "")
            description = str(
                item.get("description")
                or item.get("question")
                or MISSING_FIELD_DESCRIPTIONS.get(key, "Thiếu dữ kiện cần thiết")
            )
            items.append(
                {
                    "key": key,
                    "label": str(item.get("label") or "Dữ kiện còn thiếu"),
                    "description": description,
                    "critical": bool(item.get("critical", True)),
                    "domain": item.get("domain") or "drug_crime",
                }
            )
            continue
        key = str(item)
        items.append(
            {
                "key": key,
                "label": "Dữ kiện còn thiếu",
                "description": MISSING_FIELD_DESCRIPTIONS.get(
                    key,
                    f"Thiếu dữ kiện: {key}" if key else "Thiếu dữ kiện cần thiết",
                ),
                "critical": True,
                "domain": "drug_crime",
            }
        )
    return items


def _normalize_agentic_reasoning(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return _normalize_dict_list(raw)
    if isinstance(raw, dict):
        return [raw]
    return [{"reasoning": str(raw)}]


def _normalize_candidate_frames(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _as_list(raw):
        if isinstance(item, dict):
            plain = dict(item)
            if "article_code" not in plain and plain.get("article") is not None:
                plain["article_code"] = str(plain["article"])
            if "title" not in plain:
                plain["title"] = plain.get("crime_name") or plain.get("matched_crime") or ""
            items.append(plain)
        else:
            items.append({"title": str(item)})
    return items


def _normalize_graph_v2_agentic(data: dict[str, Any], message: str) -> dict[str, Any]:
    facts = data.get("facts")
    if hasattr(facts, "model_dump"):
        facts = facts.model_dump()
    elif not isinstance(facts, dict):
        facts = {}

    agentic_status = str(data.get("status") or "error")
    status = AGENTIC_STATUS_MAP.get(agentic_status, "insufficient_information")
    answer = str(data.get("answer") or data.get("final_answer") or "")
    candidate_frames = _normalize_candidate_frames(data.get("candidate_frames"))

    missing_facts = _normalize_agentic_missing_fields(
        data.get("missing_fields") or data.get("missing_facts")
    )
    clarifying_questions = list(data.get("clarifying_questions") or [])
    if status == "collecting_facts" and answer:
        clarifying_questions = clarifying_questions or [answer]

    debug = data.get("debug") if isinstance(data.get("debug"), dict) else {}
    if data.get("agent_trace") is not None:
        debug = dict(debug)
        debug["agent_trace"] = data.get("agent_trace")

    return {
        "question": message,
        "case_id": str(data.get("conversation_id") or data.get("case_id") or ""),
        "status": status,
        "facts": facts,
        "missing_facts": missing_facts,
        "clarifying_questions": clarifying_questions,
        "candidate_articles": candidate_frames,
        "legal_reasoning": _normalize_agentic_reasoning(data.get("reasoning")),
        "final_answer": answer,
        "confidence": _agentic_confidence_to_float(data.get("confidence")),
        "citations": _normalize_citations(data.get("citations")),
        "warnings": list(data.get("warnings") or []),
        "debug": debug or None,
        "possible_penalty_frames": candidate_frames,
        "chatbot_provider": "graph_v2",
        "graph_mode": "agentic",
    }


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


def _to_plain_dict(item: Any) -> dict[str, Any] | None:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if isinstance(item, dict):
        return item
    return None


def _normalize_dict_list(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in raw or []:
        plain = _to_plain_dict(item)
        if plain is not None:
            items.append(plain)
    return items


def _normalize_missing_facts(raw: Any) -> list[Any]:
    items: list[Any] = []
    for item in raw or []:
        plain = _to_plain_dict(item)
        items.append(plain if plain is not None else item)
    return items


def _normalize_graph_v2_legal_chat(data: dict[str, Any], message: str) -> dict[str, Any]:
    facts = data.get("facts")
    if hasattr(facts, "model_dump"):
        facts = facts.model_dump()
    elif not isinstance(facts, dict):
        facts = {}

    raw_status = str(data.get("status") or "")
    status = raw_status or "insufficient_information"
    if status not in {
        "collecting_facts",
        "ready_to_answer",
        "answered",
        "insufficient_information",
    }:
        status = AGENTIC_STATUS_MAP.get(status, "insufficient_information")

    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    try:
        case_version = int(data.get("case_version") or 0)
    except (TypeError, ValueError):
        case_version = 0

    clarification = data.get("clarification")
    if not isinstance(clarification, dict):
        clarification = None

    candidate_articles = _normalize_dict_list(data.get("candidate_articles"))
    if not candidate_articles:
        candidate_articles = _normalize_candidate_frames(data.get("candidate_frames"))

    return {
        "question": message,
        "case_id": str(data.get("case_id") or data.get("conversation_id") or ""),
        "case_version": case_version,
        "status": status,
        "facts": facts,
        "provisional_findings": _normalize_dict_list(data.get("provisional_findings")),
        "missing_facts": _normalize_missing_facts(data.get("missing_facts")),
        "clarification": clarification,
        "clarifying_questions": list(data.get("clarifying_questions") or []),
        "candidate_articles": candidate_articles,
        "legal_reasoning": _normalize_agentic_reasoning(
            data.get("legal_reasoning") or data.get("reasoning")
        ),
        "final_answer": str(data.get("final_answer") or data.get("answer") or ""),
        "confidence": confidence,
        "citations": _normalize_citations(data.get("citations")),
        "warnings": list(data.get("warnings") or []),
        "debug": data.get("debug") if isinstance(data.get("debug"), dict) else None,
        "possible_penalty_frames": _normalize_dict_list(
            data.get("possible_penalty_frames")
        )
        or _normalize_candidate_frames(data.get("candidate_frames")),
        "chatbot_provider": "graph_v2",
        "graph_mode": "legal_chat",
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

    def _require_graph_v2_base(self) -> str:
        if not self._graph_v2_base:
            raise RuntimeError(
                "CHATBOT_GRAPH_V2_URL chưa được cấu hình trên DATN backend. "
                "Hãy trỏ biến này tới service Agentic Graph RAG mới, ví dụ "
                "https://<graph-rag-agentic-service>.up.railway.app."
            )
        return self._graph_v2_base

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
        graph_desc = "Agentic Graph RAG trên Railway — Neo4j Aura riêng"
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
                name="BLHS Graph v2 · Agentic RAG",
                description=graph_desc,
                base_url=self._graph_v2_base,
                enabled=True,
                modes=["auto", "fast", "agentic"],
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

    async def forward_legal_chat(self, request: LegalChatRequest) -> dict[str, Any]:
        graph_base = self._require_graph_v2_base()
        url = f"{graph_base}/chat/legal"
        payload = {
            "message": request.message,
            "case_id": request.case_id,
            "case_version": request.case_version,
            "answers": [
                answer.model_dump(mode="json", exclude_none=False)
                for answer in request.answers
            ],
            "include_debug": request.include_debug,
            "top_k": request.top_k,
            "answer_style": request.answer_style,
        }
        logger.info("chatbot graph_v2: POST %s (structured legal chat)", url)
        data = await self._post_json(url, payload)
        return _normalize_graph_v2_legal_chat(data, request.message)

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
        graph_base = self._require_graph_v2_base()
        url = f"{graph_base}/chat/legal"
        payload = {
            "message": request.question,
            "case_id": request.conversation_id,
            "case_version": None,
            "answers": [],
            "include_debug": False,
            "top_k": request.top_k,
            "answer_style": "auto",
        }
        logger.info("chatbot graph_v2: POST %s (legacy /chat/query bridge)", url)
        data = await self._post_json(url, payload)
        return _normalize_graph_v2_legal_chat(data, request.question)

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
