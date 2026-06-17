from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.utils.text import dedupe_keep_order, normalize_text

logger = logging.getLogger(__name__)


class EntityActor(BaseModel):
    name: str
    role: str | None = None
    actions: list[str] = Field(default_factory=list)


class EntityAmount(BaseModel):
    value: float
    unit: str
    raw: str


class EntityArticleRef(BaseModel):
    article: str
    clause: str | None = None


class CaseEntities(BaseModel):
    actors: list[EntityActor] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    amounts: list[EntityAmount] = Field(default_factory=list)
    article_refs: list[EntityArticleRef] = Field(default_factory=list)
    crime_hints: list[str] = Field(default_factory=list)
    notes: str | None = None


_ARTICLE_PAT = re.compile(
    r"[ĐđDd]i[eêềế]u\s+(\d{1,3}[a-zA-Z]?)(?:\s*kho[aảáà]n\s+(\d{1,2}))?",
    re.IGNORECASE,
)
_CLAUSE_AFTER_PAT = re.compile(
    r"kho[aảáà]n\s+(\d{1,2})\s+[ĐđDd]i[eêềế]u\s+(\d{1,3}[a-zA-Z]?)",
    re.IGNORECASE,
)
_PERCENT_PAT = re.compile(r"(\d{1,3}(?:[\.,]\d+)?)\s*%")
_TITLE_PREFIX_RE = re.compile(
    r"^(?:ca\s+sĩ|nam\s+ca\s+sĩ|nữ\s+ca\s+sĩ|ông|bà|anh|chị|bị\s+can|bị\s+cáo|đối\s+tượng|người\s+tên)\s+",
    re.IGNORECASE,
)
_ACTOR_STOPWORDS = {
    "TP",
    "HCM",
    "Bộ",
    "Điều",
    "Khoản",
    "Tội",
    "Cơ",
    "Cảnh",
    "Sát",
    "Tra",
    "An",
    "Khi",
    "Nếu",
    "Người",
    "Các",
    "Ca",
    "Theo",
    "Trong",
    "Hiện",
    "Căn",
    "Do",
    "Vì",
    "Với",
    "Nam",
    "Nữ",
    "Có",
    "Công",
    "Hành",
    "Vi",
    "Lời",
    "Khai",
    "Anh",
    "Hình",
    "Thức",
    "Giao",
    "Dịch",
    "Hai",
    "NLP",
}
_NON_PERSON_PHRASES = {
    "co quan",
    "canh sat",
    "cong an",
    "tp hcm",
    "hanh vi",
    "loi khai",
    "hinh thuc",
    "giao dich",
    "chuyen an",
    "doi tuong",
    "cac tinh tiet",
    "bo luat",
}
_NON_PERSON_LOCATION_NAMES = {
    "viet nam",
    "nuoc viet nam",
    "cong hoa xa hoi chu nghia viet nam",
}
_ACTION_LIKE_SINGLE_TOKENS = {
    "dang",
    "van",
    "chuyen",
    "mua",
    "ban",
    "tang",
    "tru",
    "phat",
    "tan",
    "loan",
    "bia",
}
_PREDICATE_FOLLOWERS = {
    "thong",
    "chuyen",
    "tin",
    "tan",
    "truyen",
    "dat",
    "giu",
    "tru",
    "ban",
    "mua",
}
_ALLOWED_SINGLE_NAMES = {
    "A",
    "B",
    "C",
    "D",
    "Long",
    "Mẫn",
    "Tân",
    "Thuận",
    "Văn",
    "Tiến",
    "Sang",
    "Bí",
}
_ROLE_PATTERNS = (
    ("người nhờ/khởi xướng", r"\b{name}\s+nhờ\b"),
    ("người được nhờ", r"\bnhờ\s+{name}\b"),
    ("trung gian/liên hệ", r"\bqua\s+{name}\b"),
    ("người bán/cung cấp bị nêu tên", r"\btên\s+{name}\b"),
    ("người sử dụng", r"\b{name}\b[^.]{0,160}\b(?:sử dụng|dương tính)\b"),
    ("người đặt/chuẩn bị địa điểm", r"\b{name}\b[^.]{0,120}\bđặt\s+phòng\b"),
    ("người mua/nhờ mua", r"\b{name}\b[^.]{0,140}\b(?:mua|nhờ\s+mua|đưa\s+tiền)\b"),
    ("người giao/đem ma túy", r"\b{name}\b[^.]{0,140}\b(?:giao|đem|mang)\b[^.]{0,60}\bma\s+túy\b"),
)
_ACTION_HINTS = [
    "tàng trữ",
    "vận chuyển",
    "mua bán",
    "mua",
    "cung cấp",
    "đăng",
    "đăng thông tin",
    "phát tán",
    "loan truyền",
    "bịa đặt",
    "sử dụng",
    "tổ chức sử dụng",
    "chứa chấp",
    "rủ",
    "nhờ",
    "đặt phòng",
    "chuẩn bị",
    "giao",
    "mang",
    "đem",
    "giúp sức",
    "xúi giục",
    "chủ mưu",
    "cầm đầu",
]
_ROLE_HINTS = [
    "chủ mưu",
    "cầm đầu",
    "thực hành",
    "giúp sức",
    "xúi giục",
    "đồng phạm",
    "người mua",
    "người bán",
    "người giao",
    "người sử dụng",
]
_OBJECT_HINTS = [
    "ma túy",
    "ketamine",
    "ketamin",
    "methamphetamine",
    "mdma",
    "thuốc lắc",
    "ma túy đá",
    "gói bột",
    "viên nén",
    "tang vật",
    "heroin",
    "thông tin bịa đặt",
]


def _clean_actor_name(name: str) -> str:
    value = re.sub(r"\s+", " ", name or "").strip(" ,;:.")
    return _TITLE_PREFIX_RE.sub("", value).strip()


def _is_likely_actor_name(name: str) -> bool:
    if not name:
        return False
    norm_name = normalize_text(name)
    if norm_name == "nguoi giup viec quan ly":
        return True
    if norm_name in _NON_PERSON_LOCATION_NAMES:
        return False
    if any(phrase in norm_name for phrase in _NON_PERSON_PHRASES):
        return False
    if name in _ALLOWED_SINGLE_NAMES:
        return True
    if name in _ACTOR_STOPWORDS:
        return False
    words = name.split()
    if len(words) == 1:
        return False
    if words[0] in _ACTOR_STOPWORDS:
        return False
    return 2 <= len(words) <= 4 and all(word and word[0].isupper() for word in words)


def _next_normalized_word(text: str, end: int) -> str:
    match = re.match(r"\s+([A-Za-zÀ-ỹ]+)", text[end:] or "")
    return normalize_text(match.group(1)) if match else ""


def _has_non_person_context(text: str, start: int, end: int, candidate: str) -> bool:
    if candidate in _ALLOWED_SINGLE_NAMES:
        return False
    norm_candidate = normalize_text(candidate)
    next_word = _next_normalized_word(text, end)
    if norm_candidate == "viet" and next_word == "nam":
        return True
    if norm_candidate == "viet nam":
        return True
    if norm_candidate in _ACTION_LIKE_SINGLE_TOKENS and next_word in _PREDICATE_FOLLOWERS:
        return True
    before = normalize_text(text[max(0, start - 16):start])
    if norm_candidate in {"viet", "viet nam"} and before.split()[-1:] in (["vao"], ["tai"], ["o"], ["den"], ["tu"]):
        return True
    return False


def _add_actor(actors: list[EntityActor], seen: set[str], name: str, role: str | None = None) -> None:
    cleaned = _clean_actor_name(name)
    if not _is_likely_actor_name(cleaned):
        return
    key = normalize_text(cleaned)
    if not key or key in seen:
        if role:
            for actor in actors:
                if normalize_text(actor.name) == key and not actor.role:
                    actor.role = role
        return
    seen.add(key)
    actors.append(EntityActor(name=cleaned, role=role))


def extract_article_refs(text: str) -> list[EntityArticleRef]:
    refs: list[EntityArticleRef] = []
    seen: set[tuple[str, str | None]] = set()
    for match in _ARTICLE_PAT.finditer(text or ""):
        key = (match.group(1), match.group(2))
        if key not in seen:
            refs.append(EntityArticleRef(article=match.group(1), clause=match.group(2)))
            seen.add(key)
    for match in _CLAUSE_AFTER_PAT.finditer(text or ""):
        key = (match.group(2), match.group(1))
        if key not in seen:
            refs.append(EntityArticleRef(article=match.group(2), clause=match.group(1)))
            seen.add(key)
    return refs


def _parse_number(raw: str) -> float | None:
    try:
        value = raw.strip()
        if "," in value and "." in value:
            return float(value.replace(".", "").replace(",", "."))
        if "," in value:
            return float(value.replace(",", "."))
        if "." in value:
            left, right = value.rsplit(".", 1)
            if len(right) > 2:
                return float(value.replace(".", ""))
        return float(value)
    except ValueError:
        return None


def extract_amounts(text: str) -> list[EntityAmount]:
    norm = normalize_text(text)
    amounts: list[EntityAmount] = []
    for pattern, factor, unit in (
        (r"(\d[\d\.,]*)\s*ty(?:\s*dong)?", 1_000_000_000, "dong"),
        (r"(\d[\d\.,]*)\s*trieu(?:\s*dong)?", 1_000_000, "dong"),
        (r"(\d[\d\.,]*)\s*nghin(?:\s*dong)?", 1_000, "dong"),
    ):
        for match in re.finditer(pattern, norm):
            value = _parse_number(match.group(1))
            if value is not None:
                amounts.append(EntityAmount(value=value * factor, unit=unit, raw=match.group(0)))
    for match in _PERCENT_PAT.finditer(text or ""):
        value = _parse_number(match.group(1))
        if value is not None:
            amounts.append(EntityAmount(value=value, unit="percent", raw=match.group(0)))
    for match in re.finditer(r"(\d{1,3})\s*nguoi", norm):
        amounts.append(EntityAmount(value=float(match.group(1)), unit="nguoi", raw=match.group(0)))
    for match in re.finditer(r"(\d[\d\.]*(?:,\d+)?)\s*(?:dong|đong|đồng)", norm):
        value = _parse_number(match.group(1))
        if value is not None:
            amounts.append(EntityAmount(value=value, unit="dong", raw=match.group(0)))
    return amounts


def _regex_actors(text: str) -> list[EntityActor]:
    actors: list[EntityActor] = []
    seen: set[str] = set()
    explicit_patterns = [
        r"(?:ca\s+sĩ|nam\s+ca\s+sĩ|nữ\s+ca\s+sĩ|ông|bà|anh|chị)\s+([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){1,3})",
        r"tên\s+thật\s*:\s*([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){1,3})",
        r"người\s+tên\s+([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){0,3})",
    ]
    for pattern in explicit_patterns:
        for match in re.finditer(pattern, text or "", flags=re.I):
            _add_actor(actors, seen, match.group(1))
    for match in re.finditer(
        r"(?:ông|bà|anh|chị|bị\s+can|bị\s+cáo|đối\s+tượng|người\s+tên)?\s*"
        r"([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){0,3}|[A-ZĐ])",
        text or "",
    ):
        if _has_non_person_context(text or "", match.start(1), match.end(1), match.group(1)):
            continue
        _add_actor(actors, seen, match.group(1))
    lowered = (text or "").lower()
    for actor in actors:
        name = re.escape(actor.name.lower())
        for role, pattern in _ROLE_PATTERNS:
            if re.search(pattern.replace("{name}", name), lowered):
                actor.role = role
                break
    if "người giúp việc kiêm quản lý" in lowered or "người giúp việc" in lowered and "quản lý" in lowered:
        _add_actor(actors, seen, "Người giúp việc quản lý", "người sử dụng cùng")
    return actors


def _underthesea_actors(text: str) -> list[EntityActor]:
    try:
        from underthesea import ner as us_ner  # type: ignore
    except Exception as exc:
        logger.debug("underthesea.ner unavailable: %s", exc)
        return []
    try:
        tokens = us_ner(text)
    except Exception as exc:
        logger.warning("underthesea.ner failed: %s", exc)
        return []

    actors: list[EntityActor] = []
    current_words: list[str] = []
    current_tag: str | None = None

    def flush() -> None:
        nonlocal current_words, current_tag
        if current_words and current_tag and current_tag.endswith("PER"):
            name = " ".join(current_words).replace("_", " ").strip()
            if name:
                actors.append(EntityActor(name=name))
        current_words = []
        current_tag = None

    for item in tokens:
        if not isinstance(item, (list, tuple)) or len(item) < 4:
            continue
        word, ner_tag = str(item[0]), str(item[3])
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


def _safe_json(raw: str) -> dict[str, Any]:
    value = (raw or "").strip()
    value = re.sub(r"^```[a-zA-Z]*", "", value).strip()
    value = re.sub(r"```$", "", value).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
    return {}


def _llm_entities(text: str) -> CaseEntities | None:
    if not settings.use_llm_ner or not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Trích xuất thực thể pháp lý hình sự Việt Nam. "
                        "Chỉ trả JSON đúng schema; không suy luận tội danh chắc chắn."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Text:\n"
                        f"{text}\n\n"
                        "Schema: actors[{name, role, actions[]}], roles[], actions[], "
                        "objects[], amounts[{value, unit, raw}], article_refs[{article, clause}], "
                        "crime_hints[], notes."
                    ),
                },
            ],
        )
        return CaseEntities.model_validate(_safe_json(response.choices[0].message.content or ""))
    except Exception as exc:
        logger.warning("LLM NER skipped: %s", exc)
        return None


def _merge_actors(base: list[EntityActor], extra: list[EntityActor]) -> list[EntityActor]:
    merged: list[EntityActor] = []
    seen: set[str] = set()
    for actor in [*base, *extra]:
        name = _clean_actor_name(actor.name)
        if not _is_likely_actor_name(name):
            continue
        key = normalize_text(name)
        current = next((item for item in merged if normalize_text(item.name) == key), None)
        if current:
            if actor.role and not current.role:
                current.role = actor.role
            current.actions = dedupe_keep_order([*current.actions, *actor.actions])
            continue
        if key not in seen:
            merged.append(EntityActor(name=name, role=actor.role, actions=dedupe_keep_order(actor.actions)))
            seen.add(key)
    return _prune_actor_fragments(merged)


def _merge_actor_aliases(text: str, actors: list[EntityActor]) -> list[EntityActor]:
    alias_to_real: dict[str, str] = {}
    for match in re.finditer(
        r"([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){1,3})\s*"
        r"\(\s*tên\s+thật\s*:\s*([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){1,3})\s*\)",
        text or "",
        flags=re.I,
    ):
        alias_to_real[normalize_text(_clean_actor_name(match.group(1)))] = _clean_actor_name(match.group(2))
    if not alias_to_real:
        return actors
    by_key = {normalize_text(actor.name): actor for actor in actors}
    for alias_key, real_name in alias_to_real.items():
        real_key = normalize_text(real_name)
        alias_actor = by_key.get(alias_key)
        real_actor = by_key.get(real_key)
        if real_actor is None:
            real_actor = EntityActor(name=real_name)
            actors.append(real_actor)
            by_key[real_key] = real_actor
        if alias_actor:
            if alias_actor.role and not real_actor.role:
                real_actor.role = alias_actor.role
            real_actor.actions = dedupe_keep_order([*real_actor.actions, *alias_actor.actions])
            actors = [actor for actor in actors if normalize_text(actor.name) != alias_key]
    return actors


def _prune_actor_fragments(actors: list[EntityActor]) -> list[EntityActor]:
    by_key = {normalize_text(actor.name): actor for actor in actors}
    drop: set[str] = set()
    for key, actor in list(by_key.items()):
        words = key.split()
        if len(words) != 1:
            continue
        if any(key in other_key.split() for other_key in by_key if other_key != key and len(other_key.split()) > 1):
            drop.add(key)
    result: list[EntityActor] = []
    seen: set[str] = set()
    for actor in actors:
        key = normalize_text(actor.name)
        if key in drop or key in seen:
            continue
        result.append(actor)
        seen.add(key)
    return result


def _regex_entities(text: str) -> CaseEntities:
    norm = normalize_text(text)
    return CaseEntities(
        actors=_regex_actors(text),
        roles=[role for role in _ROLE_HINTS if normalize_text(role) in norm],
        actions=[action for action in _ACTION_HINTS if normalize_text(action) in norm],
        objects=[obj for obj in _OBJECT_HINTS if normalize_text(obj) in norm],
        amounts=extract_amounts(text),
        article_refs=extract_article_refs(text),
        crime_hints=["nhóm tội phạm về ma túy"] if "ma tuy" in norm else [],
    )


def _merge_entities(base: CaseEntities, extra: CaseEntities) -> CaseEntities:
    return CaseEntities(
        actors=_merge_actors(base.actors, extra.actors),
        roles=dedupe_keep_order([*base.roles, *extra.roles]),
        actions=dedupe_keep_order([*base.actions, *extra.actions]),
        objects=dedupe_keep_order([*base.objects, *extra.objects]),
        amounts=[*base.amounts, *[item for item in extra.amounts if (item.value, item.unit, item.raw) not in {(a.value, a.unit, a.raw) for a in base.amounts}]],
        article_refs=[
            *base.article_refs,
            *[
                item
                for item in extra.article_refs
                if (item.article, item.clause) not in {(ref.article, ref.clause) for ref in base.article_refs}
            ],
        ],
        crime_hints=dedupe_keep_order([*base.crime_hints, *extra.crime_hints]),
        notes=base.notes or extra.notes,
    )


@lru_cache(maxsize=256)
def _extract_cached(norm: str, original: str) -> CaseEntities:
    del norm
    base = _regex_entities(original)
    underthesea = CaseEntities(actors=_underthesea_actors(original))
    merged = _merge_entities(base, underthesea)
    llm = _llm_entities(original)
    if llm:
        merged = _merge_entities(merged, llm)
    merged.actors = _prune_actor_fragments(_merge_actor_aliases(original, merged.actors))
    return merged


def extract_entities(text: str) -> CaseEntities:
    original = (text or "").strip()
    if not original:
        return CaseEntities()
    return _extract_cached(normalize_text(original), original)
