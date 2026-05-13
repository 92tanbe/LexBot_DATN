"""Multi-query rewriting + HyDE cho retrieval phap ly.

Muc tieu:
- Giu query goc/sub-query theo actor.
- Sinh them query ngan theo can cu phap ly, nguong tien, vai tro, dieu luat.
- Sinh HyDE document: mot doan "tai lieu gia dinh" de embedding search bat dung ngu canh.

LLM HyDE la tuy chon; khi khong co OpenAI/API loi thi fallback rule-based van hoat dong.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.nlp.decomposer import SubQuery
from app.nlp.ner import CaseEntities

logger = logging.getLogger(__name__)


@dataclass
class RewrittenQuery:
    """Mot query dung rieng cho retrieval."""

    text: str
    source: str
    actor_name: str | None = None
    role_hint: str | None = None
    is_hyde: bool = False


def _normalize_key(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


def _append_unique(items: list[RewrittenQuery], item: RewrittenQuery, seen: set[str]) -> None:
    text = re.sub(r"\s+", " ", (item.text or "").strip())
    if not text:
        return
    key = _normalize_key(text)
    if key in seen:
        return
    seen.add(key)
    item.text = text
    items.append(item)


def _format_money_band(value: float) -> str | None:
    if value >= 500_000_000:
        return "Chiếm đoạt tài sản trị giá 500.000.000 đồng trở lên"
    if value >= 200_000_000:
        return "Chiếm đoạt tài sản trị giá từ 200.000.000 đồng đến dưới 500.000.000 đồng"
    if value >= 50_000_000:
        return "Chiếm đoạt tài sản trị giá từ 50.000.000 đồng đến dưới 200.000.000 đồng"
    return None


def _is_medical_negligence_context(question: str, entities: CaseEntities) -> bool:
    text = _normalize_key(
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
        any(term in text for term in medical_terms)
        and any(term in text for term in death_terms)
        and any(term in text for term in mistake_terms)
    )


def _rule_based_queries(
    question: str,
    entities: CaseEntities,
    sub_queries: list[SubQuery],
    seen: set[str],
) -> list[RewrittenQuery]:
    """Sinh query theo rule tu entities, khong goi model."""
    items: list[RewrittenQuery] = []

    _append_unique(items, RewrittenQuery(text=question, source="original", is_hyde=False), seen)
    for sq in sub_queries:
        _append_unique(
            items,
            RewrittenQuery(
                text=sq.text,
                source="sub_query",
                actor_name=sq.actor_name,
                role_hint=sq.role_hint,
            ),
            seen,
        )

    for hint in entities.crime_hints[:3]:
        _append_unique(
            items,
            RewrittenQuery(text=f"{hint} căn cứ cấu thành tội danh và khung hình phạt", source="crime_hint"),
            seen,
        )

    for ref in entities.article_refs[:4]:
        article_text = f"Điều {ref.article}"
        if ref.clause is not None:
            article_text += f" khoản {ref.clause}"
        _append_unique(
            items,
            RewrittenQuery(text=f"{article_text} BLHS điều kiện áp dụng và hình phạt", source="article_ref"),
            seen,
        )
        _append_unique(
            items,
            RewrittenQuery(text=f"Hình phạt bổ sung {article_text} BLHS", source="additional_penalty"),
            seen,
        )

    for amount in entities.amounts:
        if amount.unit != "dong":
            continue
        band = _format_money_band(amount.value)
        if not band:
            continue
        suffix = ""
        if entities.article_refs:
            suffix = " " + " ".join(f"Điều {r.article}" for r in entities.article_refs[:2])
        _append_unique(
            items,
            RewrittenQuery(text=f"{band}{suffix}", source="amount_threshold"),
            seen,
        )

    for role in (entities.roles or [])[:3]:
        _append_unique(
            items,
            RewrittenQuery(text=f"Vai trò {role} trong đồng phạm trách nhiệm hình sự", source="role_hint", role_hint=role),
            seen,
        )

    for actor in entities.actors[:4]:
        role_part = f" vai trò {actor.vai_tro}" if actor.vai_tro else ""
        action_part = ", ".join(actor.hanh_vi[:3] or entities.actions[:3]) or "hành vi phạm tội"
        _append_unique(
            items,
            RewrittenQuery(
                text=f"{actor.name} {action_part}{role_part} trách nhiệm hình sự",
                source="actor_legal_query",
                actor_name=actor.name,
                role_hint=actor.vai_tro,
            ),
            seen,
        )

    if _is_medical_negligence_context(question, entities):
        for query in (
            "Tội vô ý làm chết người do vi phạm quy tắc nghề nghiệp hoặc quy tắc hành chính Điều 129",
            "Bác sĩ kê nhầm thuốc làm bệnh nhân tử vong lỗi vô ý nghề nghiệp Điều 129",
            "Vô ý làm chết người trong hoạt động khám chữa bệnh không phải ma túy Điều 129",
            "Tội vô ý làm chết người Điều 128 so sánh với Điều 129",
            "Hình phạt bổ sung Điều 129 cấm hành nghề",
        ):
            _append_unique(
                items,
                RewrittenQuery(text=query, source="medical_negligence"),
                seen,
            )

    return items


def _rule_based_hyde(question: str, entities: CaseEntities, sub_queries: list[SubQuery]) -> str:
    """Tao HyDE document ngan, uu tien keyword phap ly de vector search."""
    parts: list[str] = [f"Tình huống pháp lý giả định: {question}"]
    if entities.crime_hints:
        parts.append("Tội danh cần tra cứu: " + ", ".join(entities.crime_hints[:3]) + ".")
    if entities.article_refs:
        refs = []
        for ref in entities.article_refs[:4]:
            refs.append(f"Điều {ref.article}" + (f" khoản {ref.clause}" if ref.clause else ""))
        parts.append("Điều luật trọng tâm: " + ", ".join(refs) + ".")
        parts.append("Cần xem cả cấu thành cơ bản, khung tăng nặng và hình phạt bổ sung của các điều này.")
    money_bands = [
        band
        for amount in entities.amounts
        if amount.unit == "dong"
        for band in [_format_money_band(amount.value)]
        if band
    ]
    if money_bands:
        parts.append("Ngưỡng định khung tài sản: " + "; ".join(money_bands[:2]) + ".")
    if entities.roles:
        parts.append("Vai trò đồng phạm cần phân biệt: " + ", ".join(entities.roles[:4]) + ".")
    if _is_medical_negligence_context(question, entities):
        parts.append(
            "Ngữ cảnh y khoa: bác sĩ hoặc nhân viên y tế kê/cấp nhầm thuốc làm bệnh nhân tử vong. "
            "Cần ưu tiên Điều 129 về vô ý làm chết người do vi phạm quy tắc nghề nghiệp hoặc quy tắc hành chính; "
            "đây là thuốc chữa bệnh thông thường, không phải ma túy."
        )
    if sub_queries:
        parts.append("Các nhánh truy vấn: " + " | ".join(sq.text for sq in sub_queries[:4]) + ".")
    return " ".join(parts)


def _safe_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


def _llm_hyde(question: str, entities: CaseEntities) -> tuple[str | None, list[str]]:
    """Sinh HyDE + query rewrite bang LLM, fallback silent khi loi."""
    if not settings.enable_llm_hyde or not settings.openai_api_key:
        return None, []
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.info("Bo qua LLM HyDE vi openai SDK loi: %s", exc)
        return None, []

    prompt = f"""
Câu hỏi:
{question}

Entities đã trích:
{entities.model_dump_json(indent=2)}

Hãy tạo dữ liệu phục vụ retrieval pháp lý BLHS, không kết luận cuối cùng.
Chỉ trả JSON:
{{
  "hyde": "Một đoạn văn pháp lý giả định 120-180 từ, nêu tội danh/điều/khoản/tình tiết cần tra cứu nếu có căn cứ từ entities.",
  "queries": ["3-5 query pháp lý ngắn, không bịa điều luật nếu entities không có"]
}}
""".strip()

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "Bạn tạo HyDE và query rewrite cho retrieval pháp lý. Chỉ trả JSON.",
                },
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM HyDE loi, dung fallback rule-based: %s", exc)
        return None, []

    raw = resp.choices[0].message.content if resp.choices else ""
    data = _safe_json(raw)
    hyde = data.get("hyde") if isinstance(data.get("hyde"), str) else None
    queries_raw = data.get("queries") if isinstance(data.get("queries"), list) else []
    queries = [q for q in queries_raw if isinstance(q, str)]
    return hyde, queries


def rewrite_queries(
    question: str,
    entities: CaseEntities,
    sub_queries: list[SubQuery],
    max_queries: int | None = None,
    enable_llm_hyde: bool | None = None,
) -> list[RewrittenQuery]:
    """Public API: sinh danh sach query retrieval da rewrite + HyDE."""
    keep = max_queries or settings.rewritten_query_max
    seen: set[str] = set()
    rewritten = _rule_based_queries(question, entities, sub_queries, seen)

    hyde_text = _rule_based_hyde(question, entities, sub_queries)
    _append_unique(
        rewritten,
        RewrittenQuery(text=hyde_text, source="hyde_rule", is_hyde=True),
        seen,
    )

    should_call_llm = settings.enable_llm_hyde if enable_llm_hyde is None else enable_llm_hyde
    if should_call_llm:
        llm_hyde, llm_queries = _llm_hyde(question, entities)
        if llm_hyde:
            _append_unique(
                rewritten,
                RewrittenQuery(text=llm_hyde, source="hyde_llm", is_hyde=True),
                seen,
            )
        for query in llm_queries[: settings.llm_rewrite_query_max]:
            _append_unique(
                rewritten,
                RewrittenQuery(text=query, source="llm_rewrite"),
                seen,
            )

    if len(rewritten) <= keep:
        return rewritten

    # HyDE la query quan trong cho dense retrieval, nen giu lai khi bi cat top-k.
    selected = rewritten[:keep]
    if not any(q.is_hyde for q in selected):
        first_hyde = next((q for q in rewritten if q.is_hyde), None)
        if first_hyde is not None and keep > 1:
            selected = selected[: keep - 1] + [first_hyde]
    return selected


__all__ = ["RewrittenQuery", "rewrite_queries"]
