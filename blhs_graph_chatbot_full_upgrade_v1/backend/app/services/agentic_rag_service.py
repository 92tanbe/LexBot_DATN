from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import settings
from app.models.agentic import (
    AgentAction,
    AgentTraceStep,
    AgenticChatRequest,
    AgenticChatResponse,
    LegalFacts,
    LegalReasoningObservation,
    MissingInfoResult,
)
from app.models.facts import ExtractedFacts
from app.models.legal_output import LegalReasoningItem
from app.services import graph_retriever
from app.services.answer_generator import generate_answer
from app.services.context_builder import build_context_text, citations_from_contexts
from app.services.conversation_state import conversation_state_store
from app.services.decomposer import decompose_query
from app.services.fact_extractor import extract_facts
from app.services.hybrid_retriever import retrieve_candidates
from app.services.legal_matcher import detect_missing_facts
from app.services.legal_reasoner import reason_over_contexts
from app.services.normalizer import normalize_text_with_graph
from app.services.query_rewriter import rewrite_queries
from app.services.reranker import rerank
from app.services.validator import validate_answer
from app.utils.text import normalize_text

logger = logging.getLogger(__name__)


DRUG_ACT_TO_ARTICLE = {
    "tàng trữ": "249",
    "vận chuyển": "250",
    "mua bán": "251",
    "sản xuất": "248",
    "tổ chức sử dụng": "255",
    "chứa chấp": "256",
}

SUBSTANCE_ALIASES = [
    ("ma túy đá", "methamphetamine"),
    ("methamphetamine", "methamphetamine"),
    ("meth", "methamphetamine"),
    ("đá", "methamphetamine"),
    ("hàng trắng", "heroin"),
    ("heroin", "heroin"),
    ("cần sa", "cannabis"),
    ("thuốc lắc", "mdma"),
    ("mdma", "mdma"),
    ("ketamine", "ketamine"),
    ("ketamin", "ketamine"),
    ("ma túy", "unknown_drug"),
]


class AgentTrace:
    def __init__(self) -> None:
        self.steps: list[AgentTraceStep] = []

    def add(self, action: str, tool: str, result: Any) -> None:
        self.steps.append(AgentTraceStep(step=len(self.steps) + 1, action=action, tool=tool, result=result))


def _first_article_ref(text: str) -> list[str]:
    return re.findall(r"[Đđ]iều\s+(\d+[a-zA-Z]?)", text or "")


def _parse_quantity_g(text: str) -> tuple[float | None, str | None, float | None]:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*(kg|kilogram|g|gam|gram|mg|miligam)", text or "", flags=re.I)
    if not match:
        return None, None, None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    if unit in {"kg", "kilogram"}:
        grams = value * 1000
    elif unit in {"mg", "miligam"}:
        grams = value / 1000
    else:
        grams = value
        unit = "g"
    return value, unit, grams


def _detect_intent(text: str, facts: ExtractedFacts) -> str:
    norm = normalize_text(text)
    if facts.article_refs or re.search(r"\bdieu\s+\d+", norm):
        if any(term in norm for term in ["quy dinh gi", "noi dung", "tra cuu", "tim dieu"]):
            return "article_lookup"
    if any(term in norm for term in ["bi phat bao nhieu", "khung hinh phat", "muc phat", "bao nhieu nam"]):
        return "penalty_prediction"
    if any(term in norm for term in ["co pham toi", "toi gi", "toi danh"]):
        return "crime_identification"
    if facts.actions or facts.substances or facts.quantities:
        return "case_analysis"
    if any(term in norm for term in ["blhs", "hinh su", "dieu luat"]):
        return "general_legal_question"
    return "unknown"


def _detect_domain(text: str, facts: ExtractedFacts) -> str:
    norm = normalize_text(text)
    if facts.substances or "ma tuy" in norm or "heroin" in norm or "can sa" in norm:
        return "drug_crime"
    if any(term in norm for term in ["cuop", "trom", "lua dao", "tai san", "chiem doat"]):
        return "property_crime"
    if any(term in norm for term in ["danh", "thuong tich", "chet nguoi", "bao luc"]):
        return "violence_crime"
    if any(term in norm for term in ["giao thong", "lai xe", "nong do con"]):
        return "traffic_crime"
    if any(term in norm for term in ["blhs", "hinh su", "pham toi"]):
        return "criminal_law"
    return "unknown"


def _agent_facts(text: str, extracted: ExtractedFacts) -> LegalFacts:
    norm = normalize_text(text)
    act = "unknown"
    for candidate in ["tổ chức sử dụng", "chứa chấp", "tàng trữ", "mua bán", "vận chuyển", "sản xuất", "sử dụng"]:
        if normalize_text(candidate) in norm or candidate in extracted.actions:
            act = candidate
            break
    substance = "unknown"
    for alias, canonical in SUBSTANCE_ALIASES:
        if normalize_text(alias) in norm:
            substance = canonical
            break
    if substance == "unknown" and extracted.substances:
        substance = extracted.substances[0].name
        if substance == "ma túy":
            substance = "unknown_drug"
    value, unit, grams = _parse_quantity_g(text)
    return LegalFacts(
        intent=_detect_intent(text, extracted),
        domain=_detect_domain(text, extracted),
        act=act,
        substance=substance,
        quantity=value,
        unit=unit,
        normalized_quantity_g=grams,
        article_refs=list(dict.fromkeys([*extracted.article_refs, *_first_article_ref(text)])),
        raw_text=text,
    )


def extract_legal_facts(text: str) -> tuple[ExtractedFacts, LegalFacts]:
    extracted = extract_facts(text)
    return extracted, _agent_facts(text, extracted)


def _drug_missing_info(facts: LegalFacts) -> MissingInfoResult:
    missing: list[str] = []
    if facts.act in {"unknown", "sử dụng"}:
        missing.append("act")
    if facts.substance in {"unknown", "unknown_drug"}:
        missing.append("substance")
    if facts.normalized_quantity_g is None:
        missing.append("quantity")
    if not missing:
        return MissingInfoResult(status="sufficient")
    labels = {
        "act": "hành vi cụ thể là tàng trữ, mua bán, vận chuyển, sản xuất hay tổ chức/chứa chấp sử dụng",
        "substance": "loại ma túy",
        "quantity": "khối lượng bao nhiêu gam",
    }
    question = "Bạn cho biết thêm " + "; ".join(labels[m] for m in missing) + "."
    return MissingInfoResult(status="need_more_info", missing_fields=missing, question=question)


def _choose_mode(req: AgenticChatRequest, facts: LegalFacts) -> str:
    if req.mode in {"fast", "thinking", "agentic"}:
        return req.mode
    if req.mode == "pdf_lookup":
        return "fast"
    if facts.intent == "article_lookup":
        return "fast"
    if facts.intent in {"penalty_prediction", "crime_identification", "case_analysis"}:
        return "thinking"
    return "fast" if facts.article_refs else "thinking"


def _confidence_label(value: float) -> str:
    if value >= 0.72:
        return "high"
    if value >= 0.42:
        return "medium"
    return "low"


def _node_text(node: dict[str, Any]) -> str:
    return " ".join(str(v) for v in node.values() if isinstance(v, str))


def _best_drug_reasoning(
    facts: LegalFacts,
    contexts: list[dict],
    reasoning: list[LegalReasoningItem],
) -> LegalReasoningObservation:
    target_article = DRUG_ACT_TO_ARTICLE.get(facts.act)
    ordered = sorted(reasoning, key=lambda item: (item.article_code != target_article, -item.confidence))
    best = ordered[0] if ordered else None
    if not contexts or not best:
        return LegalReasoningObservation(status="not_found", reasoning_steps=["Không có context pháp luật đủ tin cậy từ Neo4j."])

    ctx_by_code = {str((ctx.get("article") or {}).get("article_code")): ctx for ctx in contexts}
    ctx = ctx_by_code.get(target_article or best.article_code) or ctx_by_code.get(best.article_code) or contexts[0]
    article = ctx.get("article") or {}
    crime = ctx.get("crime") or {}
    haystacks = [*(ctx.get("conditions") or []), *(ctx.get("quantity_thresholds") or [])]
    condition = None
    substance_norm = normalize_text(facts.substance)
    for item in haystacks:
        text = _node_text(item)
        norm = normalize_text(text)
        if substance_norm and substance_norm in norm:
            condition = text
            break
    if condition is None and haystacks:
        condition = _node_text(haystacks[0])

    penalty_frame = None
    frames = ctx.get("penalty_frames") or []
    if frames:
        penalty_frame = _node_text(frames[0])
    candidate_frames = [
        {
            "article_code": article.get("article_code"),
            "title": article.get("title"),
            "frame": _node_text(frame),
            "source": "Neo4j",
        }
        for frame in frames[:5]
        if _node_text(frame)
    ]
    steps = [
        f"Hành vi được xác định là {facts.act}.",
        f"Chất được chuẩn hóa là {facts.substance}.",
    ]
    if facts.normalized_quantity_g is not None:
        steps.append(f"Khối lượng {facts.normalized_quantity_g:g}g được đối chiếu với context định lượng từ Neo4j.")
    steps.append("Điều luật và khung phạt chỉ lấy từ context truy xuất, không tự sinh.")
    matched = bool(condition and penalty_frame and (not target_article or str(article.get("article_code")) == target_article))
    return LegalReasoningObservation(
        status="matched" if matched else "candidate",
        matched_article=f"Điều {article.get('article_code')}" if article.get("article_code") else None,
        matched_crime=crime.get("name"),
        matched_condition=condition,
        matched_penalty_frame=penalty_frame,
        reasoning_steps=steps,
        sources=citations_from_contexts([ctx]),
        candidate_frames=candidate_frames,
        confidence=_confidence_label(best.confidence),
    )


def _safe_template_answer(
    facts: LegalFacts,
    reasoning: LegalReasoningObservation,
    llm_unavailable: bool = False,
) -> str:
    lines = [
        "Tóm tắt dữ kiện: "
        f"hành vi {facts.act}, chất {facts.substance}, khối lượng "
        f"{facts.normalized_quantity_g:g}g." if facts.normalized_quantity_g is not None else "Tóm tắt dữ kiện chưa đủ định lượng.",
    ]
    if reasoning.matched_article:
        lines.append(f"Điều luật truy xuất được: {reasoning.matched_article}" + (f" - {reasoning.matched_crime}." if reasoning.matched_crime else "."))
    if reasoning.matched_condition:
        lines.append(f"Điều kiện/ngưỡng trong dữ liệu: {reasoning.matched_condition}")
    if reasoning.matched_penalty_frame:
        lines.append(f"Khung hình phạt trong dữ liệu: {reasoning.matched_penalty_frame}")
    if reasoning.status != "matched":
        lines.append("Mức chắc chắn còn thấp vì dữ liệu graph chưa cho phép chốt một khung duy nhất.")
    lines.append("Kết quả thực tế còn phụ thuộc kết luận giám định, tình tiết tăng nặng/giảm nhẹ, nhân thân, vai trò đồng phạm và quyết định của cơ quan tiến hành tố tụng.")
    if llm_unavailable:
        lines.append("LLM không khả dụng, câu trả lời được tạo từ pipeline retrieval + reasoning.")
    return "\n".join(lines)


def _serialize_trace(trace: AgentTrace, include_debug: bool) -> list[AgentTraceStep] | None:
    return trace.steps if include_debug else None


def _fast_lookup(req: AgenticChatRequest, facts: LegalFacts, extracted: ExtractedFacts, trace: AgentTrace) -> AgenticChatResponse:
    trace.add(AgentAction.RETRIEVE_FAST, "graph_retriever.fetch_contexts/search_articles_by_title_terms", {"mode": "fast"})
    try:
        article_codes = facts.article_refs
        if not article_codes:
            hits = graph_retriever.find_articles_by_keyword(req.message, req.top_k)
            article_codes = [str(hit.get("article_code")) for hit in hits if hit.get("article_code")]
        contexts = graph_retriever.fetch_contexts(article_codes[: req.top_k])
    except Exception as exc:  # noqa: BLE001
        trace.add(AgentAction.RETURN_ERROR_FALLBACK, "graph_retriever", {"error": str(exc)})
        return AgenticChatResponse(
            status="error",
            answer="Không truy xuất được Neo4j nên mình không thể trả lời chắc chắn. Vui lòng thử lại sau.",
            facts=facts.model_dump(),
            confidence="low",
            agent_trace=_serialize_trace(trace, req.include_debug),
            debug={"neo4j_error": str(exc)} if req.include_debug else None,
        )
    if not contexts:
        trace.add(AgentAction.RETURN_NOT_FOUND, "graph_retriever", {"retrieved_count": 0})
        return AgenticChatResponse(
            status="not_found",
            answer="Chưa tìm thấy điều luật phù hợp trong cơ sở dữ liệu Neo4j, nên mình không đưa ra kết luận pháp lý.",
            facts=facts.model_dump(),
            confidence="low",
            agent_trace=_serialize_trace(trace, req.include_debug),
        )
    trace.add(AgentAction.BUILD_CONTEXT, "context_builder.build_context_text", {"context_chars": len(build_context_text(contexts))})
    citations = citations_from_contexts(contexts)
    snippets = []
    for ctx in contexts[:3]:
        article = ctx.get("article") or {}
        snippets.append(f"Điều {article.get('article_code')}: {article.get('title')}")
    answer = "Tra cứu nhanh từ Neo4j:\n" + "\n".join(f"- {item}" for item in snippets)
    trace.add(AgentAction.RETURN_FINAL, "agentic_rag_service.fast_lookup", {"status": "answered"})
    return AgenticChatResponse(
        status="answered",
        answer=answer,
        facts=facts.model_dump(),
        citations=citations,
        confidence="medium",
        agent_trace=_serialize_trace(trace, req.include_debug),
    )


def run_agentic_rag(req: AgenticChatRequest) -> AgenticChatResponse:
    trace = AgentTrace()
    extracted, message_facts = extract_legal_facts(req.message)
    trace.add(AgentAction.EXTRACT_FACTS, "fact_extractor.extract_facts + agentic.extract_legal_facts", message_facts.model_dump())

    state = conversation_state_store.get_state(req.conversation_id)
    state = conversation_state_store.merge_facts(state.conversation_id, message_facts)
    facts = state.facts
    trace.add(
        AgentAction.MERGE_CONVERSATION_FACTS,
        "conversation_state.merge_facts",
        {"conversation_id": state.conversation_id, "facts": facts.model_dump()},
    )

    mode = _choose_mode(req, facts)
    if mode == "fast":
        response = _fast_lookup(req, facts, extracted, trace)
        response.conversation_id = state.conversation_id
        return response

    if facts.domain == "drug_crime" and facts.intent in {"penalty_prediction", "case_analysis", "crime_identification", "unknown"}:
        missing_result = _drug_missing_info(facts)
        trace.add(AgentAction.CHECK_MISSING_INFO, "agentic_rag_service._drug_missing_info", missing_result.model_dump())
        if missing_result.status == "need_more_info":
            conversation_state_store.update_last_question(state.conversation_id, missing_result.question or "")
            trace.add(AgentAction.ASK_FOLLOW_UP, "conversation_state.update_last_question", {"question": missing_result.question})
            return AgenticChatResponse(
                status="need_more_info",
                answer=missing_result.question or "Bạn cho biết thêm hành vi cụ thể, loại ma túy và khối lượng bao nhiêu gam.",
                conversation_id=state.conversation_id,
                facts=facts.model_dump(),
                missing_fields=missing_result.missing_fields,
                confidence="low",
                agent_trace=_serialize_trace(trace, req.include_debug),
            )
    else:
        generic_missing = detect_missing_facts(extracted, req.message)
        trace.add(AgentAction.CHECK_MISSING_INFO, "legal_matcher.detect_missing_facts", "no_missing_fields" if not generic_missing else generic_missing)

    try:
        normalized = normalize_text_with_graph(req.message)
        sub_queries = decompose_query(req.message, extracted)
        trace.add(AgentAction.DECOMPOSE_QUERY, "decomposer.decompose_query", {"sub_query_count": len(sub_queries)})
        rewritten = rewrite_queries(req.message, extracted, sub_queries, normalized)
        trace.add(AgentAction.REWRITE_QUERY, "query_rewriter.rewrite_queries", {"query_count": len(rewritten)})
        candidates_raw, retrieval_debug = retrieve_candidates(rewritten, extracted, normalized, req.top_k)
        if facts.act in DRUG_ACT_TO_ARTICLE:
            code = DRUG_ACT_TO_ARTICLE[facts.act]
            if code not in {str(c.get("article_code")) for c in candidates_raw}:
                candidates_raw.append({"article_code": code, "title": f"Điều {code}", "score": 0.9, "source": "agent_drug_act_controlled", "matched_terms": [facts.act]})
        trace.add(AgentAction.RETRIEVE_HYBRID, "hybrid_retriever.retrieve_candidates", {"retrieved_count": len(candidates_raw), "debug": retrieval_debug})
        candidates_raw = rerank(req.message, candidates_raw, req.top_k)
        trace.add(AgentAction.RERANK_CONTEXT, "reranker.rerank", {"reranked_count": len(candidates_raw)})
        contexts = graph_retriever.fetch_contexts([str(c.get("article_code")) for c in candidates_raw if c.get("article_code")])
        trace.add(AgentAction.RETRIEVE_GRAPH, "graph_retriever.fetch_contexts", {"retrieved_count": len(contexts)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Agentic retrieval failed: %s", exc)
        trace.add(AgentAction.RETURN_ERROR_FALLBACK, "agentic_rag_service.retrieval", {"error": str(exc)})
        return AgenticChatResponse(
            status="error",
            answer="Neo4j hoặc bước truy xuất không khả dụng, nên mình không đưa ra kết luận pháp lý để tránh suy đoán.",
            conversation_id=state.conversation_id,
            facts=facts.model_dump(),
            confidence="low",
            agent_trace=_serialize_trace(trace, req.include_debug),
            debug={"retrieval_error": str(exc)} if req.include_debug else None,
        )

    if not contexts:
        trace.add(AgentAction.RETURN_NOT_FOUND, "graph_retriever.fetch_contexts", {"retrieved_count": 0})
        return AgenticChatResponse(
            status="not_found",
            answer="Không tìm thấy nguồn pháp luật đủ liên quan trong Neo4j. Mình không chốt tội danh hoặc khung hình phạt khi thiếu nguồn truy xuất.",
            conversation_id=state.conversation_id,
            facts=facts.model_dump(),
            confidence="low",
            agent_trace=_serialize_trace(trace, req.include_debug),
        )

    missing = detect_missing_facts(extracted, req.message)
    reasoning_items = reason_over_contexts(contexts, extracted, normalized, missing)
    reasoning_obs = _best_drug_reasoning(facts, contexts, reasoning_items) if facts.domain == "drug_crime" else LegalReasoningObservation(
        status="matched" if reasoning_items and reasoning_items[0].confidence >= 0.42 else "candidate",
        matched_article=f"Điều {reasoning_items[0].article_code}" if reasoning_items else None,
        matched_crime=reasoning_items[0].crime_name if reasoning_items else None,
        candidate_frames=[pf for ctx in contexts for pf in (ctx.get("penalty_frames") or [])][:5],
        confidence=_confidence_label(reasoning_items[0].confidence if reasoning_items else 0.0),
        sources=citations_from_contexts(contexts[:3]),
    )
    trace.add(AgentAction.MATCH_LEGAL_RULES, "legal_reasoner.reason_over_contexts", reasoning_obs.model_dump())
    trace.add(AgentAction.BUILD_CONTEXT, "context_builder.build_context_text", {"context_chars": len(build_context_text(contexts))})

    llm_unavailable = not settings.openai_api_key
    if reasoning_obs.status == "not_found":
        answer = "Không đủ nguồn truy xuất từ Neo4j để kết luận. Mình không tự tạo điều luật, khoản hoặc khung hình phạt."
        confidence_value = 0.1
    else:
        force_actor_breakdown = req.mode in {"agentic", "thinking"}
        answer = generate_answer(
            req.message,
            extracted,
            contexts,
            reasoning_items,
            missing,
            force_actor_breakdown=force_actor_breakdown,
        )
        if llm_unavailable and not force_actor_breakdown:
            answer = _safe_template_answer(facts, reasoning_obs, llm_unavailable=True)
        confidence_value = max([item.confidence for item in reasoning_items], default=0.3)
    trace.add(AgentAction.GENERATE_ANSWER, "answer_generator.generate_answer or safe_template", "final_answer_created")

    answer, confidence_value, warnings = validate_answer(answer, contexts, missing, reasoning_items, confidence_value)
    trace.add(AgentAction.VALIDATE_ANSWER, "validator.validate_answer", "validated" if not warnings else {"warnings": warnings})

    citations = citations_from_contexts(contexts)
    status = "answered" if reasoning_obs.status == "matched" else "candidate"
    if reasoning_obs.status == "not_found":
        status = "not_found"
    trace.add(AgentAction.RETURN_FINAL if status == "answered" else AgentAction.RETURN_CANDIDATE, "agentic_rag_service.run_agentic_rag", {"status": status})
    return AgenticChatResponse(
        status=status,
        answer=answer,
        conversation_id=state.conversation_id,
        facts=facts.model_dump(),
        reasoning=reasoning_obs.model_dump(),
        citations=citations,
        candidate_frames=reasoning_obs.candidate_frames,
        confidence=reasoning_obs.confidence if status != "not_found" else "low",
        agent_trace=_serialize_trace(trace, req.include_debug),
        debug={"warnings": warnings, "normalized": normalized} if req.include_debug else None,
    )
