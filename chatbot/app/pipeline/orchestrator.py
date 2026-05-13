"""Orchestrator 4 giai doan cho chatbot RAG BLHS.

API `POST /rag/query`:
    - ``chat_mode=tra_cuu_pdf``: trích văn từ file PDF VB hợp nhất (dataset / ``BLHS_PDF_PATH``), giống Streamlit ``analysis_lawvn``.
    - ``chat_mode=phan_tich``: ép pipeline Neo4j + LLM đầy đủ.
    - ``chat_mode`` None + ``query_mode``: ``fast`` = tra cứu nhanh (hybrid retrieval + đồ họa điều), ``thinking`` = pipeline đầy đủ.

Stream ``/rag/query/stream``: hỗ trợ ``chat_mode`` (PDF chỉ một vài event: ``pdf_lookup_done`` → ``final``).

Pipeline "thinking", thứ tự xử lý 1 câu hỏi (theo đúng thứ tự chạy):

    Stage 1 (Query understanding):     NER + decompose + sinh Cypher candidates
    Stage 2 (Retrieval):               Hybrid retrieval (RRF) + đọc graph + dedup ứng viên
    Stage 3 (Generation):              Rerank + LLM structured output
    Stage 4 (Post-processing):         Validator + format response
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import unicodedata
from typing import AsyncGenerator

from app.core.config import settings
from app.models.legal_output import (
    ActorAnalysis,
    CaseAnalysis,
    CitationOutput,
    ToiDanhOutput,
)
from app.models.schemas import (
    ChatMode,
    ChatResponse,
    ChatResponseDebug,
    Citation,
    RetrievedChunk,
    StageEvent,
)
from app.nlp.cypher_gen import execute_candidates, generate_candidates
from app.nlp.decomposer import SubQuery, decompose
from app.nlp.ner import CaseEntities, extract_article_refs, extract_entities
from app.nlp.query_rewriter import RewrittenQuery, rewrite_queries
from app.pipeline.context_builder import (
    build_context,
    collect_known_articles,
    collect_known_rule_ids,
)
from app.pipeline.fast_response import build_fast_response
from app.pipeline.pdf_textbook import run_pdf_lookup_pipeline
from app.pipeline.prompts import SYSTEM_PROMPT, build_user_prompt
from app.postprocessing.validator import validate_case_analysis
from app.retrievers import graph as graph_retriever
from app.retrievers.hybrid import retrieve_for_query
from app.retrievers.reranker import rerank

logger = logging.getLogger(__name__)


# --------------------------- Normal hoa + boost retrieval --------------------


def _normalize_vi_rule(text: str) -> str:
    """Chuan hoa tieng Viet giong fast_response de match tu khoa."""
    t = (text or "").lower()
    t = t.replace("đ", "d")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _retrieval_fulltext_keywords(rq: RewrittenQuery, crime_keywords: list[str]) -> list[str]:
    """Ưu tiên câu rewrite cho full-text, sau ghép crime hints để không trùng lặp normalization."""
    keywords = [rq.text]
    keywords.extend(crime_keywords or [])
    seen: set[str] = set()
    out: list[str] = []
    for item in keywords:
        key = _normalize_vi_rule(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _property_violence_article_candidates(question: str) -> list[int]:
    """Vu bao luc + lay tai san / nhan / vang (vd danh ngat roi lay nhan) -> cuop/trom lien quan."""
    norm = _normalize_vi_rule(question)
    violent = any(
        p in norm
        for p in (
            "danh",
            "dung gay",
            "dung dao",
            "gay danh",
            "dung vu luc",
            "khong che",
            "ngat",
            "bat tinh",
            "vo tinh",
            "gay thuong",
            "gay chet",
        )
    )
    take_asset = any(
        p in norm
        for p in (
            "lay",
            "cuop",
            "trom",
            "chiem doat",
            "mat cap",
            "nhan",
            "vang",
            "tai san",
            "do vat",
        )
    )
    explicit_rob = "cuop" in norm or "cuop giat" in norm

    if (violent and take_asset) or explicit_rob:
        # 168 cuop, 169 cuop giat, 173 trom cap, 134 co y gay thuong tich (danh gay ngat)
        return [168, 169, 173, 134]

    return []


def _boost_property_violence_chunks(question: str) -> list[RetrievedChunk]:
    """Keo Dieu 168/169/173/134 vao context khi co tin hieu bao luc + chiếm doat tai san."""
    articles = _property_violence_article_candidates(question)
    if not articles:
        return []
    chunks: list[RetrievedChunk] = []
    for i, article in enumerate(articles):
        try:
            fetched = graph_retriever.fetch_by_article(article)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bo sung property_violence: khong fetch duoc Dieu %s: %s", article, exc)
            continue
        for j, chunk in enumerate(fetched[:4]):
            chunk.rrf_score = max(chunk.rrf_score or 0.0, 0.11 - i * 0.014 - j * 0.002)
            chunk.score = max(chunk.score or 0.0, 1.0)
            meta = dict(chunk.meta or {})
            meta["domain_boost"] = "property_violence"
            chunk.meta = meta
            chunks.append(chunk)
    return chunks


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


def _plain_fast_chunks_answer(chunks: list[RetrievedChunk], max_items: int = 8) -> str:
    """Gom cac doan trich thanh cau tra loi nhanh (plain text, FE hien thi don gian)."""
    if not chunks:
        return "Không tìm thấy đoạn văn bản pháp lý nào khớp nhanh với câu hỏi."

    lines: list[str] = [
        "Tra cứu nhanh — các đoạn liên quan nhất trong tài liệu đã chỉ mục (giống tra PDF/sách giáo khoa):",
        "",
    ]
    for i, c in enumerate(chunks[:max_items], start=1):
        ref_parts: list[str] = []
        if c.article is not None:
            ref_parts.append(f"Điều {c.article}")
        if c.clause is not None:
            ref_parts.append(f"khoản {c.clause}")
        head = ", ".join(ref_parts) if ref_parts else "Tham chiếu"
        if c.dieu_name:
            head = f"{head} ({c.dieu_name})"

        body = (c.text or "").strip().replace("\n\n", "\n").replace("\n", " ")
        max_len = 480
        if len(body) > max_len:
            body = body[: max_len - 1] + "…"

        lines.append(f"{i}. {head}")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).strip()


def _prioritize_explicit_article_chunks(
    chunks: list[RetrievedChunk],
    explicit_articles: set[int],
) -> list[RetrievedChunk]:
    """Đưa chunk trùng số điều được hỏi rõ trong câu lên đầu (sau rerank/RRF)."""
    if not explicit_articles or not chunks:
        return chunks

    def sort_key(c: RetrievedChunk) -> tuple[int, float]:
        matched = c.article is not None and int(c.article) in explicit_articles
        score = float(c.rerank_score if c.rerank_score is not None else (c.rrf_score or 0.0))
        return (1 if matched else 0, score)

    return sorted(chunks, key=sort_key, reverse=True)


def _fast_lookup_case_analysis(
    question: str,
    chunks: list[RetrievedChunk],
    explicit_article_nums: set[int] | None = None,
) -> CaseAnalysis:
    """Structured toi gian cho che do tra cuu (khong goi LLM phan tich toi danh day du)."""
    hint = (
        "Chế độ tra cứu nhanh: xếp hạng theo vector + full-text + truy graph khi có số Điều trong câu. "
        'Chọn "Phân tích (thinking)" để phân luật chi tiết qua pipeline đầy đủ.'
    )
    if not chunks:
        return CaseAnalysis(
            summary="Không có đoạn văn bản khớp rõ với yêu cầu của bạn.",
            actors=[],
            confidence="low",
            warnings=[hint],
        )

    citations_out: list[CitationOutput] = []
    for c in chunks[:5]:
        if c.article is None:
            continue
        citations_out.append(
            CitationOutput(
                article=int(c.article),
                clause=c.clause,
                rule_id=c.rule_id,
                ten_toi=c.dieu_name,
                snippet=(c.text or "")[:220],
            )
        )

    with_article = [c for c in chunks if c.article is not None]
    if not with_article:
        return CaseAnalysis(
            summary="Có các đoạn văn bản liên quan; trong chỉ mục hiện chưa gắn rõ số điều cụ thể.",
            actors=[],
            confidence="medium",
            warnings=[hint],
        )

    top = with_article[0]
    explicit = explicit_article_nums or set()
    top_has_explicit = bool(explicit) and top.article is not None and int(top.article) in explicit
    td = ToiDanhOutput(
        dieu=int(top.article) if top.article is not None else 0,
        khoan=top.clause,
        ten_toi=(top.dieu_name or "Điều khoản liên quan")[:200],
        nhom_toi=top.nhom_toi,
        vai_tro="khong xac dinh",
        ly_do="Trích xuất nhanh từ các đoạn có độ liên quan cao nhất trong cơ sở tri thức đã chỉ mục.",
        citations=citations_out,
    )
    actor = ActorAnalysis(
        name="Đoạn được trích xuất",
        vai_tro="khong xac dinh",
        toi_danh=[td],
        nhan_xet="Phần chi tiết nằm trong danh sách các đoạn bên trên.",
    )

    ref_bits: list[str] = []
    for c in chunks[:3]:
        if c.article is not None:
            bit = f"Điều {c.article}"
            if c.clause is not None:
                bit += f" k.{c.clause}"
            ref_bits.append(bit)

    summary = (
        f"Tìm thấy {len(chunks)} đoạn có thể liên quan; nổi bật: {', '.join(ref_bits)}."
        if ref_bits
        else f"Tìm thấy {len(chunks)} đoạn có thể liên quan tới yêu cầu của bạn."
    )

    return CaseAnalysis(
        summary=summary,
        actors=[actor],
        confidence="high" if top_has_explicit else "medium",
        warnings=[hint],
    )


# --------------------------- Pipeline non-stream ----------------------------


def run_pipeline(
    question: str,
    top_k: int | None = None,
    include_debug: bool = False,
) -> ChatResponse:
    """Chay pipeline 4 giai doan, tra ve ChatResponse day du."""
    fast_response = build_fast_response(question, include_debug=include_debug)
    if fast_response is not None:
        return fast_response

    timings: dict[str, float] = {}
    debug = ChatResponseDebug() if include_debug else None

    # ---------- Stage 1: Query understanding ----------
    t0 = time.time()
    entities = extract_entities(question)
    sub_queries: list[SubQuery] = decompose(question, entities)
    retrieval_queries = rewrite_queries(question, entities, sub_queries)
    cypher_candidates = generate_candidates(question, entities)
    timings["stage1_understanding_ms"] = round((time.time() - t0) * 1000, 1)

    if debug is not None:
        debug.entities = entities.model_dump()
        debug.sub_queries = [sq.text for sq in sub_queries]
        debug.rewritten_queries = [f"{q.source}: {q.text}" for q in retrieval_queries]
        debug.cypher_used = [c.cypher.strip().splitlines()[0] for c in cypher_candidates[:6]]

    # ---------- Stage 2: Hybrid retrieval ----------
    t0 = time.time()
    refs = [(r.article, r.clause) for r in entities.article_refs]
    crime_keywords = entities.crime_hints[:3]
    role_hints = list(
        {q.role_hint for q in retrieval_queries if q.role_hint}
        | {sq.role_hint for sq in sub_queries if sq.role_hint}
    )

    all_chunks: list[RetrievedChunk] = []
    for rq in retrieval_queries:
        chunks = retrieve_for_query(
            query=rq.text,
            fulltext_keywords=_retrieval_fulltext_keywords(rq, crime_keywords),
            article_refs=refs,
            role_hints=role_hints,
            top_k=settings.candidate_top_k,
        )
        all_chunks.extend(chunks)

    pv_chunks = _boost_property_violence_chunks(question)
    if pv_chunks:
        logger.info("Stage 2: bo sung %d chunk property_violence (cuop/trom/...)", len(pv_chunks))
        all_chunks.extend(pv_chunks)

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
    timings["stage2_retrieval_ms"] = round((time.time() - t0) * 1000, 1)

    if debug is not None:
        debug.retrieved = candidates

    # Graph results bo sung (de validator + context)
    t0 = time.time()
    graph_results = execute_candidates(cypher_candidates, max_run=4)
    timings["stage2_graph_ms"] = round((time.time() - t0) * 1000, 1)

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


def run_pipeline_fast(
    question: str,
    top_k: int | None = None,
    include_debug: bool = False,
) -> ChatResponse:
    """Chế độ tra cứu nhanh: vector + full-text + graph theo số Điều (regex trong câu), không LLM đầy đủ."""
    q0 = question.strip()
    fast_first = build_fast_response(q0, include_debug=include_debug)
    if fast_first is not None:
        return fast_first

    timings: dict[str, float] = {}
    debug = ChatResponseDebug() if include_debug else None

    q = q0
    regex_refs = extract_article_refs(q)
    refs = [(r.article, r.clause) for r in regex_refs]
    explicit_article_nums = {r.article for r in regex_refs}

    t0 = time.time()
    candidates = retrieve_for_query(
        query=q,
        fulltext_keywords=[q[:500]],
        article_refs=refs or None,
        role_hints=None,
        top_k=settings.candidate_top_k,
    )
    timings["stage1_retrieval_ms"] = round((time.time() - t0) * 1000, 1)

    if debug is not None:
        debug.retrieved = list(candidates)
        debug.timings_ms = timings

    keep = top_k or min(8, settings.reranker_top_k)

    if settings.enable_reranker:
        t0 = time.time()
        reranked = rerank(question, candidates, top_k=keep)
        timings["stage3_rerank_ms"] = round((time.time() - t0) * 1000, 1)
    else:
        reranked = sorted(candidates, key=lambda c: c.rrf_score, reverse=True)[:keep]

    if explicit_article_nums:
        reranked = _prioritize_explicit_article_chunks(reranked, explicit_article_nums)

    if debug is not None:
        debug.reranked = reranked
        debug.timings_ms = timings

    case = _fast_lookup_case_analysis(
        question, reranked, explicit_article_nums=explicit_article_nums or None
    )
    known_articles = collect_known_articles(reranked)
    known_rule_ids = collect_known_rule_ids(reranked)
    case, warnings = validate_case_analysis(
        case,
        known_articles=known_articles,
        known_rule_ids=known_rule_ids,
    )

    if debug is not None:
        debug.warnings.extend(warnings)
        debug.timings_ms = timings

    final_answer = _plain_fast_chunks_answer(reranked)
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
    chat_mode: ChatMode | None = None,
) -> AsyncGenerator[StageEvent, None]:
    """SSE: chat_mode tra_cuu_pdf → trích PDF; không thì pipeline phân tích + rewrite truy vấn."""
    yield StageEvent(
        stage="started",
        payload={"question": question, "chat_mode": chat_mode},
    )

    if chat_mode == "tra_cuu_pdf":
        resp = await asyncio.to_thread(run_pdf_lookup_pipeline, question, include_debug)
        structured = resp.structured if isinstance(resp.structured, dict) else {}
        yield StageEvent(
            stage="pdf_lookup_done",
            payload={
                "type": structured.get("type"),
                "matched_as": structured.get("matched_as"),
                "confidence": resp.confidence,
                "intent": structured.get("intent"),
            },
        )
        yield StageEvent(
            stage="final",
            payload={
                "final_answer": resp.final_answer,
                "structured": resp.structured,
                "citations": [c.model_dump() for c in resp.citations],
                "confidence": resp.confidence,
                "debug": resp.debug.model_dump() if resp.debug else None,
            },
        )
        return

    fast_resp = await asyncio.to_thread(build_fast_response, question, include_debug)
    if fast_resp is not None:
        yield StageEvent(
            stage="fast_path_done",
            payload={
                "intent": fast_resp.structured.get("intent"),
                "confidence": fast_resp.confidence,
            },
        )
        yield StageEvent(
            stage="final",
            payload={
                "final_answer": fast_resp.final_answer,
                "structured": fast_resp.structured,
                "citations": [c.model_dump() for c in fast_resp.citations],
                "confidence": fast_resp.confidence,
                "debug": fast_resp.debug.model_dump() if fast_resp.debug else None,
            },
        )
        return

    # Stage 1
    entities = extract_entities(question)
    sub_queries = decompose(question, entities)
    retrieval_queries = rewrite_queries(question, entities, sub_queries)
    cypher_candidates = generate_candidates(question, entities)
    yield StageEvent(
        stage="stage1_done",
        payload={
            "entities": entities.model_dump(),
            "sub_queries": [sq.text for sq in sub_queries],
            "rewritten_queries": [f"{q.source}: {q.text}" for q in retrieval_queries],
            "cypher_count": len(cypher_candidates),
        },
    )

    # Stage 2
    refs = [(r.article, r.clause) for r in entities.article_refs]
    crime_keywords = entities.crime_hints[:3]
    role_hints = list(
        {q.role_hint for q in retrieval_queries if q.role_hint}
        | {sq.role_hint for sq in sub_queries if sq.role_hint}
    )
    all_chunks: list[RetrievedChunk] = []
    for rq in retrieval_queries:
        chunks = retrieve_for_query(
            query=rq.text,
            fulltext_keywords=_retrieval_fulltext_keywords(rq, crime_keywords),
            article_refs=refs,
            role_hints=role_hints,
            top_k=settings.candidate_top_k,
        )
        all_chunks.extend(chunks)

    pv_chunks = _boost_property_violence_chunks(question)
    if pv_chunks:
        logger.info("Stream stage2: bo sung %d chunk property_violence", len(pv_chunks))
        all_chunks.extend(pv_chunks)

    dedup: dict[str, RetrievedChunk] = {}
    for c in all_chunks:
        key = c.rule_id or f"{c.crime_id}::{c.level}"
        if key not in dedup or c.rrf_score > dedup[key].rrf_score:
            dedup[key] = c
    candidates = sorted(dedup.values(), key=lambda x: x.rrf_score, reverse=True)
    candidates = candidates[: settings.candidate_top_k]

    graph_results = execute_candidates(cypher_candidates, max_run=4)

    yield StageEvent(
        stage="stage2_done",
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
