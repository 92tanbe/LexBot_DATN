"""Orchestrator 4 giai doan cho chatbot RAG BLHS.

Quy trinh xu ly 1 cau hoi:
    Stage 1 (Query understanding): NER + decompose
    Stage 2 (Retrieval):             Hybrid retrieval cho moi sub-query
    Stage 3 (Generation):           Rerank + LLM structured output
    Stage 4 (Post-processing):      Validator + format response

Co ho tro 2 mode:
    - run(question, ...)        : non-stream, tra ve ChatResponse day du
    - run_stream(question, ...) : async generator yield StageEvent SSE
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
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
    ChatMode,
    ChatResponse,
    ChatResponseDebug,
    Citation,
    RetrievedChunk,
    StageEvent,
)
from app.nlp.cypher_gen import execute_candidates, generate_candidates
from app.nlp.decomposer import SubQuery, decompose
from app.nlp.ner import CaseEntities, extract_entities
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


# --------------------------- Domain hints -----------------------------------


def _normalize_vi_for_rule(text: str) -> str:
    """Normalize tiếng Việt đơn giản để match rule domain."""
    import unicodedata

    text = (text or "").lower()
    text = text.replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _drug_article_refs(question: str, entities: CaseEntities) -> list[tuple[int, int | None]]:
    """Ép kéo các điều ma túy trọng yếu vào context khi câu hỏi có ngữ cảnh phù hợp.

    Lý do: vector/rerank có thể kéo nhầm giữa "sử dụng", "tàng trữ",
    "tổ chức sử dụng", "chứa chấp". Với nhóm ma túy, cần có đủ Điều
    249/255/256 trong context để LLM so sánh vai trò và giải thích vì sao
    người tạo điều kiện có thể chịu khung nặng hơn người chỉ sử dụng.
    """
    norm = _normalize_vi_for_rule(question)
    joined_hints = _normalize_vi_for_rule(
        " ".join((entities.actions or []) + (entities.objects or []) + (entities.crime_hints or []))
    )
    text = f"{norm} {joined_hints}"

    if not any(term in text for term in ("ma tuy", "ketamine", "thuoc lac", "heroin", "ma tuý")):
        return []

    refs: set[tuple[int, int | None]] = set()

    # Tàng trữ/cất giữ/thu giữ chất ma túy -> Điều 249.
    if any(term in text for term in ("tang tru", "cat giu", "giu", "thu giu", "tich thu", "goi", "vien")):
        refs.add((249, None))

    # Vận chuyển/di chuyển/đưa ma túy đi nơi khác -> Điều 250.
    if any(term in text for term in ("van chuyen", "cho ma tuy", "mang ma tuy", "dua ma tuy", "giao ma tuy")):
        refs.add((250, None))

    # Mua bán/cung cấp/phân phối/đưa cho người khác -> Điều 251.
    dealing_terms = (
        "mua ban",
        "ban ma tuy",
        "ban cho",
        "cung cap",
        "phan phoi",
        "giao dich",
        "tra tien",
        "nhan tien",
        "dua cho nguoi khac",
        "phat ma tuy",
        "chia ma tuy",
    )
    if any(term in text for term in dealing_terms):
        refs.add((251, None))

    # Tổ chức/chứa chấp/tạo điều kiện tại phòng/karaoke/khách sạn.
    facilitation_terms = (
        "su dung",
        "cho su dung",
        "tao dieu kien",
        "dat phong",
        "phong karaoke",
        "karaoke",
        "khach san",
        "cho muon phong",
        "chua chap",
        "to chuc",
        "canh gioi",
        "chuan bi",
    )
    if any(term in text for term in facilitation_terms):
        refs.add((255, None))  # Tổ chức sử dụng trái phép chất ma túy
        refs.add((256, None))  # Chứa chấp việc sử dụng trái phép chất ma túy

    return sorted(refs)


def _boost_domain_chunks(question: str, entities: CaseEntities) -> list[RetrievedChunk]:
    """Fetch và boost context domain đặc thù để không bị validator loại citation."""
    chunks: list[RetrievedChunk] = []
    for article, clause in _drug_article_refs(question, entities):
        if clause is not None:
            fetched = graph_retriever.fetch_by_article_clause(article, clause)
        else:
            fetched = graph_retriever.fetch_by_article(article)
        if not fetched:
            fetched = _supplemental_drug_chunks(article)
        else:
            # Với các điều ma túy nhiều khoản (249/250/251), lấy quá nhiều
            # chunk dễ chiếm hết top-k và làm thiếu 255/256. Giữ khoản 1 +
            # vài khoản tăng nặng đầu là đủ cho LLM so sánh nhiều tội danh.
            fetched = fetched[:3]
        for idx, chunk in enumerate(fetched):
            # Boost vừa đủ để các điều bắt buộc sống sót qua top-k/rerank.
            chunk.rrf_score = max(chunk.rrf_score, 0.09 - idx * 0.002)
            chunk.score = max(chunk.score, 1.0)
            chunk.meta["domain_boost"] = "drug_context"
            chunks.append(chunk)
    return chunks


def _is_medical_negligence_context(question: str, entities: CaseEntities) -> bool:
    """Nhan dien ca y khoa: ke/cap nham thuoc lam benh nhan tu vong."""
    joined = _normalize_vi_for_rule(
        " ".join(
            [
                question,
                " ".join(entities.actions or []),
                " ".join(entities.objects or []),
                " ".join(entities.crime_hints or []),
                entities.notes or "",
            ]
        )
    )
    medical_terms = (
        "bac si",
        "y si",
        "dieu duong",
        "benh vien",
        "phong kham",
        "kham benh",
        "ke don",
        "ke thuoc",
        "boc nham thuoc",
        "cap phat thuoc",
        "uong thuoc",
        "dieu tri",
    )
    death_terms = ("tu vong", "chet", "lam chet", "thiet mang")
    mistake_terms = ("nham", "sai", "vo y", "so suat", "bat can", "vi pham quy tac")
    return (
        any(term in joined for term in medical_terms)
        and any(term in joined for term in death_terms)
        and any(term in joined for term in mistake_terms)
    )


def _boost_medical_negligence_chunks(question: str, entities: CaseEntities) -> list[RetrievedChunk]:
    """Keo Dieu 129/128 cho ca bac si so suat nghe nghiep lam chet nguoi."""
    if not _is_medical_negligence_context(question, entities):
        return []

    chunks: list[RetrievedChunk] = []
    for article, base_score in ((129, 0.096), (128, 0.078)):
        try:
            fetched = graph_retriever.fetch_by_article(article)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Khong fetch duoc medical-negligence Dieu %s: %s", article, exc)
            continue
        for idx, chunk in enumerate(fetched):
            chunk.rrf_score = max(chunk.rrf_score, base_score - idx * 0.002)
            chunk.score = max(chunk.score, 1.0)
            chunk.meta["domain_boost"] = "medical_negligence"
            chunks.append(chunk)
    return chunks


def _boost_additional_penalty_chunks(candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Keo them hinh phat bo sung cua cac dieu da retrieval vao context.

    Neu dieu luat da duoc truy ra dung (vd Dieu 168) nhung khoan
    ADDITIONAL_PENALTY nam sau cac khung chinh, rerank co the loai khoan nay.
    Bo sung co kiem soat giup LLM thay du ca hinh phat chinh va hinh phat bo sung.
    """
    if not candidates:
        return []

    existing_rule_ids = {c.rule_id for c in candidates if c.rule_id}
    article_scores: dict[int, float] = {}
    for chunk in candidates:
        if chunk.article is None:
            continue
        article_scores[chunk.article] = max(
            article_scores.get(chunk.article, 0.0),
            chunk.rrf_score or chunk.score or 0.0,
        )

    boosted: list[RetrievedChunk] = []
    top_articles = [
        article
        for article, _score in sorted(article_scores.items(), key=lambda item: item[1], reverse=True)[:3]
    ]
    for article in top_articles:
        try:
            article_chunks = graph_retriever.fetch_by_article(article)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Khong fetch duoc hinh phat bo sung Dieu %s: %s", article, exc)
            continue
        for idx, chunk in enumerate(
            c for c in article_chunks if (c.logic or "").upper() == "ADDITIONAL_PENALTY"
        ):
            if chunk.rule_id and chunk.rule_id in existing_rule_ids:
                continue
            existing_rule_ids.add(chunk.rule_id or f"{chunk.article}:{chunk.clause}:{idx}")
            chunk.rrf_score = max(chunk.rrf_score, 0.07 - idx * 0.002)
            chunk.score = max(chunk.score, 1.0)
            chunk.meta["domain_boost"] = "additional_penalty"
            boosted.append(chunk)
    return boosted


def _article_candidates_by_score(candidates: list[RetrievedChunk], limit: int = 3) -> list[int]:
    article_scores: dict[int, float] = {}
    for chunk in candidates:
        if chunk.article is None:
            continue
        article_scores[chunk.article] = max(
            article_scores.get(chunk.article, 0.0),
            chunk.rrf_score or chunk.score or 0.0,
        )
    return [
        article
        for article, _score in sorted(article_scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def _boost_amount_threshold_chunks(
    entities: CaseEntities, candidates: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    """Keo them khoan co nguong tien phu hop voi so tien trong cau hoi."""
    money_amounts = [a.value for a in entities.amounts if a.unit == "dong"]
    if not money_amounts or not candidates:
        return []

    amount = max(money_amounts)
    if amount < 50_000_000:
        return []

    existing_rule_ids = {c.rule_id for c in candidates if c.rule_id}
    boosted: list[RetrievedChunk] = []

    def _matches_amount_band(text: str) -> bool:
        norm = _normalize_vi_for_rule(text)
        if amount >= 500_000_000:
            return "500.000.000" in text and ("tro len" in norm or "trở lên" in text)
        if amount >= 200_000_000:
            return "200.000.000" in text and "500.000.000" in text
        return "50.000.000" in text and "200.000.000" in text

    for article in _article_candidates_by_score(candidates):
        try:
            article_chunks = graph_retriever.fetch_by_article(article)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Khong fetch duoc khoan theo nguong tien Dieu %s: %s", article, exc)
            continue
        for chunk in article_chunks:
            if chunk.rule_id and chunk.rule_id in existing_rule_ids:
                continue
            if not _matches_amount_band(chunk.text or ""):
                continue
            existing_rule_ids.add(chunk.rule_id or f"{chunk.article}:{chunk.clause}:amount")
            chunk.rrf_score = max(chunk.rrf_score, 0.085)
            chunk.score = max(chunk.score, 1.0)
            chunk.meta["domain_boost"] = "amount_threshold"
            chunk.meta["matched_amount"] = amount
            boosted.append(chunk)
    return boosted


def _retrieval_fulltext_keywords(query: RewrittenQuery, crime_keywords: list[str]) -> list[str]:
    """Uu tien query rewrite cho fulltext, sau do moi den crime hints."""
    keywords = [query.text]
    keywords.extend(crime_keywords or [])
    seen: set[str] = set()
    out: list[str] = []
    for item in keywords:
        key = _normalize_vi_for_rule(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _supplemental_drug_chunks(article: int) -> list[RetrievedChunk]:
    """Bổ sung context luật khi dataset hiện tại thiếu Điều 255/256.

    Dataset `deepseek_merged.json` hiện chỉ có các điều ma túy chính như
    249/250/251, nhưng nhiều tình huống thực tế cần so sánh với Điều 255
    (tổ chức sử dụng) và Điều 256 (chứa chấp việc sử dụng). Nếu không đưa
    2 điều này vào context, LLM hiểu đúng nhưng validator sẽ loại citation.
    """
    supplemental: dict[int, list[dict]] = {
        255: [
            {
                "clause": 1,
                "rule_id": "255_supp_r1",
                "name": "Tội tổ chức sử dụng trái phép chất ma túy",
                "text": (
                    "Điều 255 khoản 1 - Tội tổ chức sử dụng trái phép chất ma túy. "
                    "Áp dụng với người tổ chức, rủ rê, điều hành, bố trí địa điểm, "
                    "chuẩn bị công cụ/phương tiện hoặc tạo điều kiện để người khác "
                    "sử dụng trái phép chất ma túy. Hình phạt: phạt tù từ 02 năm "
                    "đến 07 năm."
                ),
                "penalty_min": 2,
                "penalty_max": 7,
            },
            {
                "clause": 2,
                "rule_id": "255_supp_r2",
                "name": "Tội tổ chức sử dụng trái phép chất ma túy",
                "text": (
                    "Điều 255 khoản 2 - Khung tăng nặng của tội tổ chức sử dụng "
                    "trái phép chất ma túy, ví dụ phạm tội nhiều lần, đối với nhiều "
                    "người, đối với người dưới 16 tuổi hoặc các tình tiết tăng nặng "
                    "khác theo luật. Hình phạt: phạt tù từ 07 năm đến 15 năm."
                ),
                "penalty_min": 7,
                "penalty_max": 15,
            },
        ],
        256: [
            {
                "clause": 1,
                "rule_id": "256_supp_r1",
                "name": "Tội chứa chấp việc sử dụng trái phép chất ma túy",
                "text": (
                    "Điều 256 khoản 1 - Tội chứa chấp việc sử dụng trái phép chất "
                    "ma túy. Áp dụng với người cho mượn, cho thuê, bố trí hoặc để "
                    "người khác sử dụng địa điểm thuộc quyền quản lý của mình "
                    "(như phòng karaoke, nhà nghỉ, phòng riêng) để sử dụng trái phép "
                    "chất ma túy. Hình phạt: phạt tù từ 02 năm đến 07 năm."
                ),
                "penalty_min": 2,
                "penalty_max": 7,
            },
            {
                "clause": 2,
                "rule_id": "256_supp_r2",
                "name": "Tội chứa chấp việc sử dụng trái phép chất ma túy",
                "text": (
                    "Điều 256 khoản 2 - Khung tăng nặng của tội chứa chấp việc sử "
                    "dụng trái phép chất ma túy, ví dụ lợi dụng chức vụ quyền hạn, "
                    "phạm tội nhiều lần, đối với nhiều người hoặc tái phạm nguy hiểm "
                    "theo luật. Hình phạt: phạt tù từ 07 năm đến 15 năm."
                ),
                "penalty_min": 7,
                "penalty_max": 15,
            },
        ],
    }

    chunks: list[RetrievedChunk] = []
    for item in supplemental.get(article, []):
        chunks.append(
            RetrievedChunk(
                source="graph",
                level="khoan",
                text=item["text"],
                score=1.0,
                rrf_score=0.0,
                article=article,
                clause=item["clause"],
                rule_id=item["rule_id"],
                crime_id=str(article),
                dieu_name=item["name"],
                nhom_toi="Các tội phạm về ma túy",
                logic="SUPPLEMENTAL",
                meta={
                    "supplemental": True,
                    "reason": "dataset_missing_article_255_256",
                    "penalty_min": item["penalty_min"],
                    "penalty_max": item["penalty_max"],
                },
            )
        )
    return chunks


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


# ---------------------- Enrich output tu context luat ------------------------


def _extract_additional_penalty_text(chunk: RetrievedChunk) -> str:
    """Rut mo ta hinh phat bo sung tu chunk_text."""
    text = (chunk.text or "").strip()
    if not text:
        return ""

    match = re.search(
        r"(?:Hình phạt|Hinh phat)(?:\s+bổ sung|\s+bo sung)?\s*:\s*(.+)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        return re.sub(r"\s+", " ", " ".join(lines[1:])).strip()
    return re.sub(r"\s+", " ", text).strip()


def _apply_additional_penalties(
    case: CaseAnalysis, chunks: list[RetrievedChunk]
) -> CaseAnalysis:
    """Gan hinh phat bo sung vao output neu context co ADDITIONAL_PENALTY."""
    by_article: dict[int, list[RetrievedChunk]] = {}
    for chunk in chunks:
        if chunk.article is None:
            continue
        if (chunk.logic or "").upper() != "ADDITIONAL_PENALTY":
            continue
        by_article.setdefault(chunk.article, []).append(chunk)

    if not by_article:
        return case

    for actor in case.actors:
        for td in actor.toi_danh:
            additional_chunks = by_article.get(td.dieu) or []
            if not additional_chunks:
                continue

            extra_parts = [td.hinh_phat.extra] if td.hinh_phat.extra else []
            existing_extra = " ".join(extra_parts).lower()
            existing_citations = {
                (c.article, c.clause, c.rule_id) for c in td.citations
            }

            for chunk in additional_chunks:
                penalty_text = _extract_additional_penalty_text(chunk)
                if penalty_text and penalty_text.lower() not in existing_extra:
                    extra_parts.append(f"Hình phạt bổ sung: {penalty_text}")
                    existing_extra += " " + penalty_text.lower()

                cit_key = (chunk.article, chunk.clause, chunk.rule_id)
                if chunk.article is not None and cit_key not in existing_citations:
                    td.citations.append(
                        CitationOutput(
                            article=chunk.article,
                            clause=chunk.clause,
                            rule_id=chunk.rule_id,
                            ten_toi=chunk.dieu_name or td.ten_toi,
                            snippet=(chunk.text or "")[:240],
                        )
                    )
                    existing_citations.add(cit_key)

            if extra_parts:
                td.hinh_phat.extra = "; ".join(extra_parts)

    return case


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

    domain_chunks = _boost_domain_chunks(question, entities)
    if domain_chunks:
        logger.info("Stage 2: them %d drug-domain chunks vao context", len(domain_chunks))
        all_chunks.extend(domain_chunks)

    medical_chunks = _boost_medical_negligence_chunks(question, entities)
    if medical_chunks:
        logger.info("Stage 2: them %d medical-negligence chunks vao context", len(medical_chunks))
        all_chunks.extend(medical_chunks)

    amount_chunks = _boost_amount_threshold_chunks(entities, all_chunks)
    if amount_chunks:
        logger.info("Stage 2: them %d amount-threshold chunks vao context", len(amount_chunks))
        all_chunks.extend(amount_chunks)

    additional_penalty_chunks = _boost_additional_penalty_chunks(all_chunks)
    if additional_penalty_chunks:
        logger.info(
            "Stage 2: them %d additional-penalty chunks vao context",
            len(additional_penalty_chunks),
        )
        all_chunks.extend(additional_penalty_chunks)

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
    case = _apply_additional_penalties(case, candidates)
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
    chat_mode: ChatMode = "tra_cuu_pdf",
) -> AsyncGenerator[StageEvent, None]:
    """Async generator yield StageEvent qua tung giai doan.

    Neu chat_mode='tra_cuu_pdf': chi yield started -> pdf_lookup_done -> final,
    khong chay retrieval/rerank/LLM cua pipeline phan tich.

    Neu chat_mode='phan_tich':
    chi stream theo MOC giai doan: stage1_done, stage2_done, stage3_done, stage4_done, final.
    """
    yield StageEvent(stage="started", payload={"question": question, "chat_mode": chat_mode})

    if chat_mode == "tra_cuu_pdf":
        resp = await asyncio.to_thread(
            run_pdf_lookup_pipeline,
            question,
            include_debug,
        )
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

    fast_response = build_fast_response(question, include_debug=include_debug)
    if fast_response is not None:
        yield StageEvent(
            stage="fast_path_done",
            payload={
                "intent": fast_response.structured.get("intent"),
                "confidence": fast_response.confidence,
            },
        )
        yield StageEvent(
            stage="final",
            payload={
                "final_answer": fast_response.final_answer,
                "structured": fast_response.structured,
                "citations": [c.model_dump() for c in fast_response.citations],
                "confidence": fast_response.confidence,
                "debug": fast_response.debug.model_dump() if fast_response.debug else None,
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
        )
        all_chunks.extend(chunks)

    domain_chunks = _boost_domain_chunks(question, entities)
    if domain_chunks:
        all_chunks.extend(domain_chunks)

    medical_chunks = _boost_medical_negligence_chunks(question, entities)
    if medical_chunks:
        all_chunks.extend(medical_chunks)

    amount_chunks = _boost_amount_threshold_chunks(entities, all_chunks)
    if amount_chunks:
        all_chunks.extend(amount_chunks)

    additional_penalty_chunks = _boost_additional_penalty_chunks(all_chunks)
    if additional_penalty_chunks:
        all_chunks.extend(additional_penalty_chunks)

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
    case = _apply_additional_penalties(case, candidates)

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
