from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import FinalAnswer, NormalizeRequest, SearchCandidate, SearchRequest, SearchResponse
from app.services.answer_generator import generate_answer
from app.services.context_builder import citations_from_contexts
from app.services.graph_retriever import fetch_contexts
from app.services.fact_extractor import extract_facts
from app.services.fulltext_retriever import search_fulltext
from app.services.hybrid_retriever import retrieve_candidates
from app.services.legal_matcher import detect_missing_facts
from app.services.legal_reasoner import reason_over_contexts
from app.services.normalizer import normalize_endpoint_payload, normalize_text_with_graph
from app.services.query_rewriter import rewrite_queries
from app.services.decomposer import decompose_query
from app.services.reranker import rerank
from app.services.validator import validate_answer

router = APIRouter(tags=["search"])


def _article_content_from_context(ctx: dict) -> str:
    article = ctx.get("article") or {}
    if article.get("full_text"):
        return str(article.get("full_text"))

    parts: list[str] = []
    for clause in ctx.get("clauses") or []:
        clause_no = clause.get("clause_no")
        text = clause.get("text")
        if text:
            parts.append(f"Khoản {clause_no}: {text}" if clause_no else str(text))
    for point in ctx.get("points") or []:
        point_label = point.get("point_label") or point.get("point")
        text = point.get("text")
        if text:
            parts.append(f"Điểm {point_label}: {text}" if point_label else str(text))
    return "\n".join(parts)


def _enrich_candidates(candidates: list[dict], contexts: list[dict]) -> list[SearchCandidate]:
    ctx_by_code = {
        str((ctx.get("article") or {}).get("article_code")): ctx
        for ctx in contexts
        if (ctx.get("article") or {}).get("article_code")
    }
    enriched: list[SearchCandidate] = []
    for candidate in candidates:
        data = dict(candidate)
        code = str(data.get("article_code") or "")
        ctx = ctx_by_code.get(code)
        article = (ctx.get("article") or {}) if ctx else {}
        article_title = str(article.get("title") or data.get("article_title") or data.get("title") or "") or None
        data["article_code"] = code or None
        data["article_title"] = article_title
        data["article_content"] = _article_content_from_context(ctx) if ctx else data.get("article_content")
        data["matched_terms"] = data.get("matched_terms") or []
        data["sources"] = data.get("sources") or []
        data["score"] = float(data.get("score") or 0.0)
        if article_title:
            data["title"] = article_title
        enriched.append(SearchCandidate(**data))
    return enriched


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    if req.search_type == "fulltext":
        candidates = search_fulltext(req.query, req.top_k)
        contexts = fetch_contexts([str(c.get("article_code")) for c in candidates if c.get("article_code")])
        facts = extract_facts(req.query)
        missing = detect_missing_facts(facts, req.query)
        reasoning = reason_over_contexts(contexts, facts, [], missing)
        reasoning_rank = {item.article_code: idx for idx, item in enumerate(reasoning)}
        contexts = sorted(contexts, key=lambda ctx: reasoning_rank.get(str((ctx.get("article") or {}).get("article_code")), 999))
        answer = generate_answer(req.query, facts, contexts, reasoning, missing)
        answer, _, warnings = validate_answer(answer, contexts, missing, reasoning, 0.5)
        debug = {"mode": "fulltext", "warnings": warnings} if req.include_debug else None
        return SearchResponse(
            query=req.query,
            candidates=_enrich_candidates(candidates, contexts),
            final_answer=FinalAnswer(content=answer, warnings=warnings),
            missing_facts=missing,
            citations=citations_from_contexts(contexts),
            debug=debug,
        )
    facts = extract_facts(req.query)
    normalized = normalize_text_with_graph(req.query)
    sub = decompose_query(req.query, facts)
    rewritten = rewrite_queries(req.query, facts, sub, normalized)
    candidates, debug = retrieve_candidates(rewritten, facts, normalized, req.top_k)
    candidates = rerank(req.query, candidates, req.top_k)
    seen = {str(c.get("article_code")) for c in candidates}
    action_norms = {a.lower() for a in facts.actions}
    required_crime_codes: list[str] = []
    if facts.substances:
        if "tổ chức sử dụng" in action_norms:
            required_crime_codes.append("255")
        if "sử dụng" in action_norms:
            required_crime_codes.append("256a")
        if "mua" in action_norms or "mua bán" in action_norms:
            required_crime_codes.extend(["251", "249"])
    for code in required_crime_codes:
        if code not in seen:
            candidates.append({"article_code": code, "title": f"Điều {code}", "score": 0.05, "source": "required_drug_action", "matched_terms": [f"Điều {code}"]})
            seen.add(code)
    contexts = fetch_contexts([str(c.get("article_code")) for c in candidates if c.get("article_code")])
    missing = detect_missing_facts(facts, req.query)
    reasoning = reason_over_contexts(contexts, facts, normalized, missing)
    reasoning_rank = {item.article_code: idx for idx, item in enumerate(reasoning)}
    reasoning_score = {item.article_code: item.confidence for item in reasoning}
    contexts = sorted(contexts, key=lambda ctx: reasoning_rank.get(str((ctx.get("article") or {}).get("article_code")), 999))
    context_titles = {
        str((ctx.get("article") or {}).get("article_code")): str((ctx.get("article") or {}).get("title") or "")
        for ctx in contexts
    }
    for candidate in candidates:
        code = str(candidate.get("article_code"))
        if code in reasoning_score:
            candidate["score"] = max(float(candidate.get("score") or 0.0), float(reasoning_score[code]))
            candidate["reason"] = "ranked_by_legal_reasoning"
        if context_titles.get(code):
            candidate["title"] = context_titles[code]
    candidates = sorted(candidates, key=lambda c: reasoning_rank.get(str(c.get("article_code")), 999))
    answer = generate_answer(req.query, facts, contexts, reasoning, missing)
    answer, _, warnings = validate_answer(answer, contexts, missing, reasoning, 0.5)
    if req.include_debug:
        debug["warnings"] = warnings
        debug["facts"] = facts.model_dump()
    return SearchResponse(
        query=req.query,
        candidates=_enrich_candidates(candidates, contexts),
        final_answer=FinalAnswer(content=answer, warnings=warnings),
        missing_facts=missing,
        citations=citations_from_contexts(contexts),
        debug=debug if req.include_debug else None,
    )


@router.post("/normalize")
def normalize(req: NormalizeRequest) -> dict:
    return normalize_endpoint_payload(req.text)
