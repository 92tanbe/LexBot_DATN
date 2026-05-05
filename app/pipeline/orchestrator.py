"""Orchestrator 4 giai doan cho chatbot RAG BLHS.

Quy trinh xu ly 1 cau hoi:
    Stage 2 (Query understanding):  NER + decompose
    Stage 1 (Retrieval):            Hybrid retrieval cho moi sub-query
    Stage 3 (Generation):           Rerank + LLM structured output
    Stage 4 (Post-processing):      Validator + format response

Co ho tro 2 mode:
    - run(question, ...)        : non-stream, tra ve ChatResponse day du
    - run_stream(question, ...) : async generator yield StageEvent SSE
"""
from __future__ import annotations

import json
import logging
import time
from typing import AsyncGenerator

from app.core.config import settings
from app.models.legal_output import (
    ActorAnalysis,
    CaseAnalysis,
    CitationOutput,
    ToiDanhOutput,
)
from app.models.schemas import (
    ChatResponse,
    ChatResponseDebug,
    Citation,
    RetrievedChunk,
    StageEvent,
)
from app.nlp.cypher_gen import execute_candidates, generate_candidates
from app.nlp.decomposer import SubQuery, decompose
from app.nlp.ner import CaseEntities, extract_entities
from app.pipeline.context_builder import (
    build_context,
    collect_known_articles,
    collect_known_rule_ids,
)
from app.pipeline.prompts import SYSTEM_PROMPT, build_user_prompt
from app.postprocessing.validator import validate_case_analysis
from app.retrievers.hybrid import retrieve_for_query
from app.retrievers.reranker import rerank

logger = logging.getLogger(__name__)


# --------------------------- LLM client ------------------------------------


def _llm_client() -> tuple[object | None, str | None]:
    """Tra ve (client, error_message). Neu OK thi error_message = None."""
    if not settings.openai_api_key:
        return None, "OPENAI_API_KEY rong - kiem tra chatbot/.env"
    try:
        from openai import OpenAI
    except Exception as exc:  # noqa: BLE001
        return None, f"openai SDK chua cai dat: {exc}"
    try:
        return OpenAI(api_key=settings.openai_api_key), None
    except Exception as exc:  # noqa: BLE001
        return None, f"Khoi tao OpenAI client loi: {exc}"


def _call_llm_for_analysis(
    question: str, entities: CaseEntities, context: str
) -> tuple[CaseAnalysis | None, str | None]:
    """Goi LLM. Tra ve (case, error_message).

    Khi case is None thi error_message luon co gia tri de orchestrator
    ghi vao warnings cho frontend debug.
    """
    client, err = _llm_client()
    if client is None:
        logger.warning("Stage 3 LLM khong san sang: %s", err)
        return None, err

    user_prompt = build_user_prompt(
        question=question,
        entities_json=entities.model_dump_json(indent=2),
        context=context,
    )

    logger.info(
        "Stage 3: goi LLM model=%s system_chars=%d user_chars=%d context_chars=%d",
        settings.openai_model,
        len(SYSTEM_PROMPT),
        len(user_prompt),
        len(context),
    )

    try:
        resp = client.chat.completions.create(  # type: ignore[attr-defined]
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"LLM call exception: {type(exc).__name__}: {exc}"
        logger.exception("Stage 3 LLM call failed")
        return None, msg

    raw = resp.choices[0].message.content if resp.choices else ""
    if not raw:
        return None, "LLM tra ve content rong"

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("LLM JSON parse loi: %s. Raw[:300]=%s", exc, raw[:300])
        return None, f"LLM JSON parse loi: {exc}"

    try:
        case = CaseAnalysis.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CaseAnalysis validate loi: %s", exc)
        return None, f"CaseAnalysis schema validate loi: {exc}"

    logger.info(
        "Stage 3 LLM OK: %d actor, confidence=%s, finish=%s",
        len(case.actors),
        case.confidence,
        getattr(resp.choices[0], "finish_reason", "?") if resp.choices else "?",
    )
    return case, None


# ---------------------- Fallback khi LLM khong san sang ---------------------


def _fallback_case_analysis(
    question: str,
    chunks: list[RetrievedChunk],
    llm_error: str | None = None,
) -> CaseAnalysis:
    """Tao CaseAnalysis don gian khi LLM that bai. llm_error duoc dua vao warnings."""
    base_warning = (
        f"LLM khong san sang ({llm_error}), output la fallback"
        if llm_error
        else "LLM khong san sang, output la fallback"
    )

    if not chunks:
        return CaseAnalysis(
            summary="Khong tim thay can cu phap ly phu hop trong co so du lieu.",
            actors=[],
            confidence="low",
            warnings=["Khong co context retrieval", base_warning],
        )

    top = chunks[0]
    citations: list[CitationOutput] = []
    for c in chunks[:3]:
        if c.article is not None:
            citations.append(
                CitationOutput(
                    article=c.article,
                    clause=c.clause,
                    rule_id=c.rule_id,
                    ten_toi=c.dieu_name,
                    snippet=(c.text or "")[:200],
                )
            )

    toi_danh = ToiDanhOutput(
        dieu=top.article or 0,
        khoan=top.clause,
        ten_toi=top.dieu_name or "Khong xac dinh",
        nhom_toi=top.nhom_toi,
        vai_tro="khong xac dinh",
        ly_do="Du doan dua tren retrieval, chua co LLM phan tich chi tiet.",
        citations=citations,
    )

    actor = ActorAnalysis(
        name="Nguoi pham toi",
        vai_tro="khong xac dinh",
        toi_danh=[toi_danh],
        nhan_xet="(Phan tich tu dong khi LLM khong san sang.)",
    )

    return CaseAnalysis(
        summary=f"Truong hop co the lien quan toi {top.dieu_name or 'mot toi danh'} (Dieu {top.article}).",
        actors=[actor],
        confidence="low",
        warnings=[base_warning],
    )


# --------------------------- Helper render ----------------------------------


def _render_final_answer(case: CaseAnalysis) -> str:
    """Render markdown ngan tu CaseAnalysis."""
    lines: list[str] = []
    lines.append(f"**Tom tat:** {case.summary}")
    lines.append("")
    for actor in case.actors:
        lines.append(f"### Doi tuong: {actor.name} ({actor.vai_tro})")
        if actor.nhan_xet:
            lines.append(actor.nhan_xet)
        for td in actor.toi_danh:
            head = f"- **Dieu {td.dieu}**"
            if td.khoan:
                head += f" khoan {td.khoan}"
            head += f": {td.ten_toi}"
            lines.append(head)
            hp = td.hinh_phat
            hp_parts = []
            if hp.min is not None and hp.max is not None:
                hp_parts.append(f"{hp.min}-{hp.max} {hp.don_vi or ''}".strip())
            elif hp.min is not None:
                hp_parts.append(f"tu {hp.min} {hp.don_vi or ''}".strip())
            if hp.extra:
                hp_parts.append(hp.extra)
            if hp_parts:
                lines.append(f"  - Hinh phat: {'; '.join(hp_parts)}")
            if td.tinh_tiet_tang_nang:
                lines.append(f"  - Tang nang: {', '.join(td.tinh_tiet_tang_nang[:3])}")
            if td.tinh_tiet_giam_nhe:
                lines.append(f"  - Giam nhe: {', '.join(td.tinh_tiet_giam_nhe[:3])}")
        lines.append("")
    if case.overall_advice:
        lines.append(f"**Loi khuyen:** {case.overall_advice}")
    if case.warnings:
        lines.append("\n**Canh bao:** " + "; ".join(case.warnings))
    lines.append(f"\n_Do tin cay: {case.confidence}_")
    return "\n".join(lines).strip()


def _to_citations(case: CaseAnalysis) -> list[Citation]:
    cites: list[Citation] = []
    seen: set[tuple[int, int | None, str | None]] = set()
    for actor in case.actors:
        for td in actor.toi_danh:
            for c in td.citations:
                key = (c.article, c.clause, c.rule_id)
                if key in seen:
                    continue
                seen.add(key)
                cites.append(
                    Citation(
                        article=c.article,
                        clause=c.clause,
                        rule_id=c.rule_id,
                        ten_toi=c.ten_toi or td.ten_toi,
                        snippet=c.snippet,
                    )
                )
    return cites


# --------------------------- Pipeline non-stream ----------------------------


def run_pipeline(
    question: str,
    top_k: int | None = None,
    include_debug: bool = False,
) -> ChatResponse:
    """Chay pipeline 4 giai doan, tra ve ChatResponse day du."""
    timings: dict[str, float] = {}
    debug = ChatResponseDebug() if include_debug else None

    # ---------- Stage 2: Query understanding ----------
    t0 = time.time()
    entities = extract_entities(question)
    sub_queries: list[SubQuery] = decompose(question, entities)
    cypher_candidates = generate_candidates(question, entities)
    timings["stage2_understanding_ms"] = round((time.time() - t0) * 1000, 1)

    if debug is not None:
        debug.entities = entities.model_dump()
        debug.sub_queries = [sq.text for sq in sub_queries]
        debug.cypher_used = [c.cypher.strip().splitlines()[0] for c in cypher_candidates[:6]]

    # ---------- Stage 1: Hybrid retrieval ----------
    t0 = time.time()
    refs = [(r.article, r.clause) for r in entities.article_refs]
    crime_keywords = entities.crime_hints[:3]
    role_hints = list({sq.role_hint for sq in sub_queries if sq.role_hint})

    all_chunks: list[RetrievedChunk] = []
    for sq in sub_queries:
        chunks = retrieve_for_query(
            query=sq.text,
            fulltext_keywords=crime_keywords or [sq.text],
            article_refs=refs,
            role_hints=role_hints,
            top_k=settings.candidate_top_k,
        )
        all_chunks.extend(chunks)

    # Dedupe theo rule_id/crime_id, giu rrf score cao nhat
    dedup: dict[str, RetrievedChunk] = {}
    for c in all_chunks:
        key = c.rule_id or f"{c.crime_id}::{c.level}"
        if key in dedup:
            if c.rrf_score > dedup[key].rrf_score:
                dedup[key].merge_provenance(c)
                dedup[key].rrf_score = c.rrf_score
        else:
            dedup[key] = c
    candidates = sorted(dedup.values(), key=lambda x: x.rrf_score, reverse=True)
    candidates = candidates[: settings.candidate_top_k]
    timings["stage1_retrieval_ms"] = round((time.time() - t0) * 1000, 1)

    if debug is not None:
        debug.retrieved = candidates

    # Graph results bo sung (de validator + context)
    t0 = time.time()
    graph_results = execute_candidates(cypher_candidates, max_run=4)
    timings["stage1_graph_ms"] = round((time.time() - t0) * 1000, 1)

    # ---------- Stage 3: Rerank + Generation ----------
    t0 = time.time()
    keep = top_k or settings.reranker_top_k
    reranked = rerank(question, candidates, top_k=keep)
    timings["stage3_rerank_ms"] = round((time.time() - t0) * 1000, 1)

    if debug is not None:
        debug.reranked = reranked

    context_str = build_context(reranked, graph_results=graph_results)

    t0 = time.time()
    case, llm_error = _call_llm_for_analysis(question, entities, context_str)
    timings["stage3_llm_ms"] = round((time.time() - t0) * 1000, 1)

    if case is None:
        case = _fallback_case_analysis(question, reranked, llm_error=llm_error)

    # ---------- Stage 4: Post-processing ----------
    t0 = time.time()
    known_articles = collect_known_articles(reranked)
    known_rule_ids = collect_known_rule_ids(reranked)
    case, warnings = validate_case_analysis(
        case,
        known_articles=known_articles,
        known_rule_ids=known_rule_ids,
    )
    timings["stage4_validate_ms"] = round((time.time() - t0) * 1000, 1)

    if debug is not None:
        debug.timings_ms = timings
        debug.warnings.extend(warnings)

    final_answer = _render_final_answer(case)
    citations = _to_citations(case)

    return ChatResponse(
        question=question,
        final_answer=final_answer,
        structured=case.model_dump(),
        citations=citations,
        confidence=case.confidence,
        debug=debug,
    )


# ----------------------------- Streaming ------------------------------------


async def run_pipeline_stream(
    question: str,
    top_k: int | None = None,
    include_debug: bool = True,
) -> AsyncGenerator[StageEvent, None]:
    """Async generator yield StageEvent qua tung giai doan.

    Khong stream LLM token cap thap (de don gian),
    chi stream theo MOC giai doan: stage2_done, stage1_done, stage3_done, stage4_done, final.
    """
    yield StageEvent(stage="started", payload={"question": question})

    # Stage 2
    entities = extract_entities(question)
    sub_queries = decompose(question, entities)
    cypher_candidates = generate_candidates(question, entities)
    yield StageEvent(
        stage="stage2_done",
        payload={
            "entities": entities.model_dump(),
            "sub_queries": [sq.text for sq in sub_queries],
            "cypher_count": len(cypher_candidates),
        },
    )

    # Stage 1
    refs = [(r.article, r.clause) for r in entities.article_refs]
    role_hints = list({sq.role_hint for sq in sub_queries if sq.role_hint})
    all_chunks: list[RetrievedChunk] = []
    for sq in sub_queries:
        chunks = retrieve_for_query(
            query=sq.text,
            fulltext_keywords=entities.crime_hints[:3] or [sq.text],
            article_refs=refs,
            role_hints=role_hints,
        )
        all_chunks.extend(chunks)

    dedup: dict[str, RetrievedChunk] = {}
    for c in all_chunks:
        key = c.rule_id or f"{c.crime_id}::{c.level}"
        if key not in dedup or c.rrf_score > dedup[key].rrf_score:
            dedup[key] = c
    candidates = sorted(dedup.values(), key=lambda x: x.rrf_score, reverse=True)
    candidates = candidates[: settings.candidate_top_k]

    graph_results = execute_candidates(cypher_candidates, max_run=4)

    yield StageEvent(
        stage="stage1_done",
        payload={
            "retrieved_count": len(candidates),
            "graph_runs": len(graph_results),
            "preview": [
                {
                    "article": c.article,
                    "clause": c.clause,
                    "rule_id": c.rule_id,
                    "rrf_score": round(c.rrf_score, 4),
                    "dieu_name": c.dieu_name,
                }
                for c in candidates[:8]
            ],
        },
    )

    # Stage 3
    keep = top_k or settings.reranker_top_k
    reranked = rerank(question, candidates, top_k=keep)
    yield StageEvent(
        stage="stage3_rerank_done",
        payload={
            "kept": [
                {
                    "article": c.article,
                    "clause": c.clause,
                    "rule_id": c.rule_id,
                    "rerank_score": c.rerank_score,
                }
                for c in reranked
            ]
        },
    )

    context_str = build_context(reranked, graph_results=graph_results)
    case, llm_error = _call_llm_for_analysis(question, entities, context_str)
    if case is None:
        case = _fallback_case_analysis(question, reranked, llm_error=llm_error)

    yield StageEvent(
        stage="stage3_llm_done",
        payload={
            "confidence": case.confidence,
            "llm_error": llm_error,
        },
    )

    # Stage 4
    known_articles = collect_known_articles(reranked)
    known_rule_ids = collect_known_rule_ids(reranked)
    case, warnings = validate_case_analysis(case, known_articles, known_rule_ids)

    yield StageEvent(
        stage="stage4_done", payload={"warnings": warnings, "confidence": case.confidence}
    )

    final_answer = _render_final_answer(case)
    citations = _to_citations(case)

    yield StageEvent(
        stage="final",
        payload={
            "final_answer": final_answer,
            "structured": case.model_dump(),
            "citations": [c.model_dump() for c in citations],
            "confidence": case.confidence,
        },
    )
