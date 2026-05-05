"""Hybrid NER cho cau hoi phap ly hinh su.

Quy trinh:
    1. Baseline: dung underthesea de tach token + NER (PER, ORG, LOC).
    2. Regex: trich tham chieu Dieu/Khoan, so tien (trieu/ti/dong), ti le %.
    3. LLM: dung gpt-4o-mini voi structured output de bo sung
       - actors (ten + vai tro du doan)
       - actions (giet, cuop, ...)
       - roles (chu muu, dong pham, giup suc, xui giuc)
       - objects (tai san, vu khi, nan nhan)
       - amounts.

Cache LRU theo cau hoi da chuan hoa de tranh goi LLM lap.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)


# ----------------------------- Schema --------------------------------------


class Actor(BaseModel):
    name: str
    vai_tro: str | None = None
    hanh_vi: list[str] = Field(default_factory=list)


class Amount(BaseModel):
    value: float
    unit: str  # dong, nguoi, percent, year, ...
    raw: str


class ArticleRef(BaseModel):
    article: int
    clause: int | None = None


class CaseEntities(BaseModel):
    actors: list[Actor] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    amounts: list[Amount] = Field(default_factory=list)
    article_refs: list[ArticleRef] = Field(default_factory=list)
    crime_hints: list[str] = Field(default_factory=list)
    notes: str | None = None


# --------------------------- Regex helpers ---------------------------------

_ARTICLE_PAT = re.compile(
    r"[ĐđDd]i[eêềế]u\s+(\d{1,3})(?:\s*kho[aảáà]n\s+(\d{1,2}))?",
    re.IGNORECASE,
)
_CLAUSE_AFTER_PAT = re.compile(
    r"kho[aảáà]n\s+(\d{1,2})\s+[ĐđDd]i[eêềế]u\s+(\d{1,3})",
    re.IGNORECASE,
)
_PERCENT_PAT = re.compile(r"(\d{1,3}(?:[\.,]\d+)?)\s*%")
_NUMBER_PAT = re.compile(r"(\d[\d\.,]*)")


def _normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


def extract_article_refs(text: str) -> list[ArticleRef]:
    """Trich tham chieu Dieu X (khoan Y) tu cau hoi."""
    refs: list[ArticleRef] = []
    seen: set[tuple[int, int | None]] = set()

    for match in _ARTICLE_PAT.finditer(text or ""):
        article = int(match.group(1))
        clause = int(match.group(2)) if match.group(2) else None
        key = (article, clause)
        if key not in seen:
            refs.append(ArticleRef(article=article, clause=clause))
            seen.add(key)

    for match in _CLAUSE_AFTER_PAT.finditer(text or ""):
        clause = int(match.group(1))
        article = int(match.group(2))
        key = (article, clause)
        if key not in seen:
            refs.append(ArticleRef(article=article, clause=clause))
            seen.add(key)

    return refs


def extract_amounts(text: str) -> list[Amount]:
    """Trich so tien / ti le / so nguoi tu cau hoi tieng Viet."""
    text_norm = _normalize_text(text)
    amounts: list[Amount] = []

    for raw_num, factor, unit_label in (
        (r"(\d[\d\.,]*)\s*ty(?:\s*dong)?", 1_000_000_000, "dong"),
        (r"(\d[\d\.,]*)\s*trieu(?:\s*dong)?", 1_000_000, "dong"),
        (r"(\d[\d\.,]*)\s*nghin(?:\s*dong)?", 1_000, "dong"),
    ):
        for m in re.finditer(raw_num, text_norm):
            try:
                value = float(m.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                continue
            amounts.append(
                Amount(value=value * factor, unit=unit_label, raw=m.group(0))
            )

    for m in _PERCENT_PAT.finditer(text or ""):
        try:
            value = float(m.group(1).replace(",", "."))
            amounts.append(Amount(value=value, unit="percent", raw=m.group(0)))
        except ValueError:
            continue

    for m in re.finditer(r"(\d{1,3})\s*ng[uư][oơ]i", text_norm):
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        amounts.append(Amount(value=value, unit="nguoi", raw=m.group(0)))

    return amounts


# --------------------------- underthesea baseline --------------------------


def _underthesea_ner(text: str) -> list[Actor]:
    """Goi underthesea.ner, gop thanh Actor."""
    try:
        from underthesea import ner as us_ner  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("Khong load duoc underthesea.ner: %s", exc)
        return []

    try:
        tokens = us_ner(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("underthesea.ner loi: %s", exc)
        return []

    actors: list[Actor] = []
    current_words: list[str] = []
    current_tag: str | None = None

    def flush():
        nonlocal current_words, current_tag
        if current_words and current_tag and current_tag.endswith("PER"):
            name = " ".join(current_words).strip()
            if name:
                actors.append(Actor(name=name))
        current_words = []
        current_tag = None

    for item in tokens:
        if not isinstance(item, (list, tuple)) or len(item) < 4:
            continue
        word, _pos, _chunk, ner_tag = item[0], item[1], item[2], item[3]
        if ner_tag.startswith("B-"):
            flush()
            current_tag = ner_tag[2:]
            current_words = [word]
        elif ner_tag.startswith("I-") and current_tag == ner_tag[2:]:
            current_words.append(word)
        else:
            flush()

    flush()
    return actors


# --------------------------- LLM extraction --------------------------------


_LLM_SYSTEM_PROMPT = (
    "Ban la tro ly phap ly chuyen ve Bo luat Hinh su Viet Nam. "
    "Tu cau hoi nguoi dung, hay trich xuat thong tin co cau truc theo schema JSON sau. "
    "Chi tra ve JSON, khong giai thich, khong markdown."
)

_LLM_USER_TEMPLATE = """
Cau hoi: {question}

Hay tra loi BANG JSON THUAN voi cau truc:
{{
  "actors": [{{"name": "...", "vai_tro": "chinh pham|dong pham|chu muu|giup suc|xui giuc|nan nhan|null", "hanh_vi": ["..."]}}],
  "roles": ["chu muu", "dong pham", ...],
  "actions": ["giet nguoi", "cuop tai san", ...],
  "objects": ["tai san", "vu khi", "nan nhan duoi 16 tuoi", ...],
  "amounts": [{{"value": 500000000, "unit": "dong", "raw": "500 trieu"}}],
  "article_refs": [{{"article": 168, "clause": 2}}],
  "crime_hints": ["toi cuop tai san", "toi giet nguoi"],
  "notes": "ghi chu ngan ve case"
}}

Nguyen tac:
- Neu cau hoi neu nhieu nguoi (vd: A, B, C), tach moi nguoi thanh 1 actor.
- Neu khong xac dinh duoc thi de mang rong [].
- Voi 'vai_tro', uu tien 4 gia tri: chinh pham, dong pham, chu muu, giup suc, xui giuc.
- 'crime_hints' la ten toi danh chuan (vd: "toi cuop tai san"), khong phai mo ta.
- Tra ve JSON DUNG cu phap, khong them ` ``` `.
"""


def _safe_load_json(text: str) -> dict[str, Any]:
    """Parse JSON, robust voi truong hop LLM tra ke them code fence."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {}


def _llm_extract(question: str) -> CaseEntities | None:
    """Goi gpt-4o-mini voi JSON mode."""
    if not settings.openai_api_key:
        logger.info("Khong co OPENAI_API_KEY, bo qua LLM NER")
        return None

    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("openai SDK chua cai dat: %s", exc)
        return None

    client = OpenAI(api_key=settings.openai_api_key)
    try:
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": _LLM_USER_TEMPLATE.format(question=question)},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM NER goi loi: %s", exc)
        return None

    raw = resp.choices[0].message.content if resp.choices else ""
    data = _safe_load_json(raw)
    if not data:
        return None

    try:
        return CaseEntities.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM NER parse loi: %s", exc)
        return None


# --------------------------- Public API ------------------------------------


def _merge_entities(
    base: CaseEntities,
    underthesea_actors: list[Actor],
    refs_regex: list[ArticleRef],
    amounts_regex: list[Amount],
) -> CaseEntities:
    """Hop nhat ket qua tu nhieu nguon, uu tien LLM nhung lay them tu regex."""
    actor_names = {a.name.lower() for a in base.actors}
    for a in underthesea_actors:
        if a.name.lower() not in actor_names:
            base.actors.append(a)
            actor_names.add(a.name.lower())

    seen_refs = {(r.article, r.clause) for r in base.article_refs}
    for r in refs_regex:
        if (r.article, r.clause) not in seen_refs:
            base.article_refs.append(r)
            seen_refs.add((r.article, r.clause))

    seen_amounts = {(a.value, a.unit) for a in base.amounts}
    for a in amounts_regex:
        if (a.value, a.unit) not in seen_amounts:
            base.amounts.append(a)
            seen_amounts.add((a.value, a.unit))

    return base


@lru_cache(maxsize=256)
def _extract_cached(question_norm: str, original: str) -> CaseEntities:
    """Lan extract co cache theo question da chuan hoa."""
    refs_regex = extract_article_refs(original)
    amounts_regex = extract_amounts(original)
    underthesea_actors = _underthesea_ner(original)

    llm_result = _llm_extract(original)
    if llm_result is None:
        base = CaseEntities()
    else:
        base = llm_result

    return _merge_entities(base, underthesea_actors, refs_regex, amounts_regex)


def extract_entities(question: str) -> CaseEntities:
    """Public: trich entity tu cau hoi nguoi dung."""
    question = (question or "").strip()
    if not question:
        return CaseEntities()
    norm = _normalize_text(question)
    return _extract_cached(norm, question)
