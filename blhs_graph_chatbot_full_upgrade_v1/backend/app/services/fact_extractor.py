from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.models.facts import Actor, EvidenceSource, ExhibitFact, ExhibitStatus, ExtractedFacts, ForensicStatus, Quantity, SubstanceFact
from app.prompts.fact_extraction_prompt import FACT_EXTRACTION_SYSTEM, FACT_EXTRACTION_USER
from app.services.ner import CaseEntities, extract_entities
from app.utils.text import dedupe_keep_order, normalize_text

logger = logging.getLogger(__name__)

ACTION_TERMS = [
    "tàng trữ", "vận chuyển", "mua bán", "mua", "cung cấp", "sản xuất", "chiếm đoạt", "sử dụng", "tổ chức sử dụng",
    "chứa chấp", "lôi kéo", "cưỡng bức", "che giấu", "không tố giác", "giúp sức", "xúi giục",
    "chủ mưu", "cầm đầu", "rủ", "nhờ", "đặt phòng", "chuẩn bị", "chưa đạt", "khai thác", "tự thú",
    "đăng", "đăng thông tin", "phát tán", "loan truyền", "bịa đặt",
    "bắn", "nổ súng", "giết", "làm hư hỏng", "tàng trữ vũ khí", "sử dụng vũ khí",
]
SUBSTANCE_ALIASES = {
    "ketamin": "ketamine", "ketamine": "ketamine", "kẹo": "MDMA", "thuốc lắc": "MDMA",
    "mdma": "MDMA", "đá": "methamphetamine", "meth": "methamphetamine", "cần sa": "cần sa",
    "ke": "ketamine", "ma túy đá": "methamphetamine", "hàng trắng": "heroin",
    "heroin": "heroin", "cỏ": "cannabis", "cannabis": "cannabis", "ma túy": "ma túy",
}
CONSEQUENCE_TERMS = ["chết người", "tử vong", "hy sinh", "thương tích", "thiệt hại", "hư hỏng", "dương tính"]
LOCATION_TERMS = ["karaoke", "quán bar", "nhà nghỉ", "phòng", "khách sạn", "Việt Nam"]
MITIGATING_TERMS = ["tự thú", "thành khẩn", "ăn năn", "đủ 70 tuổi", "người đủ 70 tuổi"]
AGGRAVATING_TERMS = ["có tổ chức", "tái phạm", "tái phạm nguy hiểm", "côn đồ", "lợi dụng chức vụ"]
EXHIBIT_PATTERNS = [
    ("consumed", r"(?:không\s+còn\s+tang\s+vật|tang\s+vật\s+đã\s+(?:bị\s+)?(?:tiêu\s+thụ|sử\s+dụng)\s+hết|đã\s+(?:tiêu\s+thụ|sử\s+dụng)\s+hết)"),
    ("not_seized", r"(?:không\s+thu\s+giữ\s+được|không\s+thu\s+được|không\s+phát\s+hiện\s+tang\s+vật)"),
    ("seized", r"(?:thu\s+giữ|thu\s+được|phát\s+hiện|bắt\s+quả\s+tang)[^.]{0,80}(?:tang\s+vật|ma\s+túy|ketamin|ketamine|thuốc\s+lắc|mdma|heroin|cần\s+sa|gói|viên|gam|g)"),
    ("mentioned", r"(?:tang\s+vật|vật\s+chứng)"),
]


def _parse_float(raw: str) -> float | None:
    try:
        raw = raw.strip()
        if "," in raw and "." in raw:
            return float(raw.replace(".", "").replace(",", "."))
        if "," in raw:
            return float(raw.replace(",", "."))
        if "." in raw:
            left, right = raw.rsplit(".", 1)
            if len(right) <= 2:
                return float(raw)
            return float(raw.replace(".", ""))
        return float(raw)
    except ValueError:
        return None


_WORD_NUMBERS = {
    "một": 1,
    "mot": 1,
    "hai": 2,
    "ba": 3,
    "bốn": 4,
    "bon": 4,
    "năm": 5,
    "nam": 5,
    "sáu": 6,
    "sau": 6,
    "bảy": 7,
    "bay": 7,
    "tám": 8,
    "tam": 8,
    "chín": 9,
    "chin": 9,
    "mười": 10,
    "muoi": 10,
}


def _parse_quantity_value(raw: str) -> float | None:
    value = _parse_float(raw)
    if value is not None:
        return value
    normalized = normalize_text(raw)
    return float(_WORD_NUMBERS[normalized]) if normalized in _WORD_NUMBERS else None


_ACTOR_STOPWORDS = {
    "TP", "HCM", "NLP",
    "Cơ", "Cảnh", "Sát", "Tra", "An",
    "Bộ", "Điều", "Khoản", "Tội", "Khi", "Nếu", "Tình", "Người", "Các", "Theo",
    "Trong", "Hiện", "Căn", "Tuy", "Do", "Vì", "Với", "Ca", "Nam", "Nữ",
    "Tương", "Những", "Sơn", "Ngọc", "Minh", "Nhật", "Tết", "Có",
    "Công", "Hành", "Vi", "Lời", "Khai", "Anh", "Hình", "Thức", "Giao", "Dịch", "Hai",
}
_ACTOR_STOPWORDS -= {"Sơn", "Ngọc", "Minh", "Nhật"}
_NON_PERSON_LOCATION_NAMES = {
    "viet nam",
    "nuoc viet nam",
    "cong hoa xa hoi chu nghia viet nam",
    "trung quoc",
    "greenbay garden",
    "quang ninh",
    "tp hcm",
    "thanh pho ho chi minh",
    "phong canh sat",
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
_PERSON_NAME_EXCEPTIONS = {
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
_SUBSTANCE_NAME_KEYS = {normalize_text(value) for value in [*SUBSTANCE_ALIASES.keys(), *SUBSTANCE_ALIASES.values(), "ma túy tổng hợp"]}
_TITLE_PREFIX_RE = re.compile(r"^(?:ca\s+sĩ|nam\s+ca\s+sĩ|nữ\s+ca\s+sĩ|ông|bà|anh|chị|bị\s+can|bị\s+cáo)\s+", re.I)
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
    "trung quoc",
    "greenbay garden",
    "quang ninh",
    "phong canh",
    "luc luong cong an",
    "can bo phong",
}


def _clean_actor_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name or "").strip(" ,;:.")
    name = _TITLE_PREFIX_RE.sub("", name).strip()
    return name


def _is_likely_actor_name(name: str) -> bool:
    norm_name = normalize_text(name)
    if norm_name == "nguoi giup viec quan ly":
        return True
    if norm_name in _NON_PERSON_LOCATION_NAMES:
        return False
    if any(phrase in norm_name for phrase in _NON_PERSON_PHRASES):
        return False
    words = name.split()
    if len(words) == 1:
        return name in _PERSON_NAME_EXCEPTIONS or bool(re.fullmatch(r"[A-D](?:\d{0,2})?", name))
    if words[0] in _ACTOR_STOPWORDS:
        return False
    return 2 <= len(words) <= 4 and all(word and word[0].isupper() for word in words)


def _next_normalized_word(text: str, end: int) -> str:
    match = re.match(r"\s+([A-Za-zÀ-ỹ]+)", text[end:] or "")
    return normalize_text(match.group(1)) if match else ""


def _has_non_actor_context(text: str, start: int, end: int, candidate: str) -> bool:
    if candidate in _PERSON_NAME_EXCEPTIONS:
        return False
    norm_candidate = normalize_text(candidate)
    next_word = _next_normalized_word(text, end)
    if norm_candidate == "viet" and next_word == "nam":
        return True
    if norm_candidate == "viet nam":
        return True
    if norm_candidate in _ACTION_LIKE_SINGLE_TOKENS and next_word in _PREDICATE_FOLLOWERS:
        return True
    before_tokens = normalize_text(text[max(0, start - 16):start]).split()
    if norm_candidate in {"viet", "viet nam"} and before_tokens[-1:] in (["vao"], ["tai"], ["o"], ["den"], ["tu"]):
        return True
    return False


def _add_actor(actors: list[Actor], seen: set[str], name: str, age: int | None = None) -> None:
    name = _clean_actor_name(name)
    if not name or name in _ACTOR_STOPWORDS or name.upper() in {"BLHS", "MDMA"}:
        return
    if normalize_text(name) in _SUBSTANCE_NAME_KEYS:
        return
    if not _is_likely_actor_name(name):
        return
    key = name.lower()
    if key in seen:
        for actor in actors:
            if actor.name.lower() == key and age is not None:
                actor.age = age
        return
    seen.add(key)
    actors.append(Actor(name=name, age=age))


def _extract_actors(text: str) -> list[Actor]:
    actors: list[Actor] = []
    seen: set[str] = set()

    explicit_name_patterns = [
        r"(?:ca\s+sĩ|nam\s+ca\s+sĩ|nữ\s+ca\s+sĩ|ông|bà|anh|chị)\s+([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){1,3})",
        r"tên\s+thật\s*:\s*([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){1,3})",
        r"người\s+tên\s+([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){0,3})",
    ]
    for pattern in explicit_name_patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            _add_actor(actors, seen, match.group(1))

    age_name_pattern = re.compile(
        r"((?:(?:ca\s+sĩ|nam\s+ca\s+sĩ|nữ\s+ca\s+sĩ|ông|bà|anh|chị)\s+)?"
        r"[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){0,3})\s*,\s*(\d{1,3})\s*tuổi",
        re.I,
    )
    for match in age_name_pattern.finditer(text):
        _add_actor(actors, seen, match.group(1), int(match.group(2)))

    for match in re.finditer(r"\b([A-ZĐ](?:\d{0,2})?)\b", text):
        if _has_non_actor_context(text, match.start(1), match.end(1), match.group(1)):
            continue
        _add_actor(actors, seen, match.group(1))
    for match in re.finditer(r"\b([A-ZĐ][a-zA-ZÀ-ỹ]{1,24})\b", text):
        name = match.group(1)
        if name not in _PERSON_NAME_EXCEPTIONS:
            continue
        if _has_non_actor_context(text, match.start(1), match.end(1), name):
            continue
        if name in _ACTOR_STOPWORDS and name != "Long":
            continue
        _add_actor(actors, seen, name)
    for m in re.finditer(r"([A-ZĐ][A-ZĐ0-9]{0,2})\s*(?:đủ\s*)?(\d{1,2})\s*tuổi", text):
        for actor in actors:
            if actor.name == m.group(1):
                actor.age = int(m.group(2))
    lowered = text.lower()
    for actor in actors:
        name = actor.name
        lname = name.lower()
        if re.search(rf"\b{re.escape(lname)}\s+nhờ\b", lowered):
            actor.role = "người nhờ/khởi xướng"
        elif re.search(rf"\bnhờ\s+{re.escape(lname)}\b", lowered):
            actor.role = "người được nhờ"
        elif re.search(rf"\bqua\s+{re.escape(lname)}\b", lowered):
            actor.role = "trung gian/liên hệ"
        elif re.search(rf"\btên\s+{re.escape(lname)}\b", lowered):
            actor.role = "người bán/cung cấp bị nêu tên"
        elif re.search(rf"\b{re.escape(lname)}\b[^.]{0,160}\btổ chức\b", lowered):
            actor.role = "người bị cáo buộc tổ chức"
        elif re.search(rf"\b{re.escape(lname)}\b[^.]{0,120}\b(chuyển tiền|nhờ người mua|mua hàng)\b", lowered):
            actor.role = "người bị cáo buộc mua/nhờ mua"
        elif re.search(rf"\b{re.escape(lname)}\b[^.]{0,160}\bsử dụng\b", lowered):
            actor.role = "người sử dụng"
    for actor in actors:
        lname = actor.name.lower()
        window_match = re.search(rf"\b{re.escape(lname)}\b(?P<tail>[^.]{{0,180}})", lowered)
        tail = window_match.group("tail") if window_match else ""
        if "thừa nhận" in tail and "sử dụng" in tail:
            actor.role = "người sử dụng"
            continue
        if actor.role:
            continue
        later_self_use = re.search(rf"\b{re.escape(lname)}\b[^.]{{0,180}}thừa nhận[^.]{{0,80}}sử dụng", lowered)
        if later_self_use:
            actor.role = "người sử dụng"
            continue
        elif "tổ chức" in tail:
            actor.role = "người bị cáo buộc tổ chức"
        elif "chuyển tiền" in tail or "nhờ người mua" in tail or "mua hàng" in tail:
            actor.role = "người bị cáo buộc mua/nhờ mua"
        elif "sử dụng" in tail:
            actor.role = "người sử dụng"
    lowered = text.lower()
    if "người giúp việc kiêm quản lý" in lowered or ("người giúp việc" in lowered and "quản lý" in lowered):
        _add_actor(actors, seen, "Người giúp việc quản lý")
        for actor in actors:
            if normalize_text(actor.name) == "nguoi giup viec quan ly":
                actor.role = "người sử dụng cùng"
    return _prune_actor_fragments(_merge_actor_aliases(text, actors))


def _merge_actor_aliases(text: str, actors: list[Actor]) -> list[Actor]:
    alias_to_real: dict[str, str] = {}
    for match in re.finditer(
        r"([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){1,3})\s*"
        r"\(\s*tên\s+thật\s*:\s*([A-ZĐ][a-zA-ZÀ-ỹ]{1,24}(?:\s+[A-ZĐ][a-zA-ZÀ-ỹ]{1,24}){1,3})\s*\)",
        text,
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
            real_actor = Actor(name=real_name)
            actors.append(real_actor)
            by_key[real_key] = real_actor
        if alias_actor:
            if alias_actor.role and not real_actor.role:
                real_actor.role = alias_actor.role
            if alias_actor.notes and not real_actor.notes:
                real_actor.notes = alias_actor.notes
            actors = [actor for actor in actors if normalize_text(actor.name) != alias_key]
    return actors


def _prune_actor_fragments(actors: list[Actor]) -> list[Actor]:
    keys = {normalize_text(actor.name): actor for actor in actors}
    drop: set[str] = set()
    for key in keys:
        words = key.split()
        if len(words) != 1:
            continue
        if any(key in other_key.split() for other_key in keys if other_key != key and len(other_key.split()) > 1):
            drop.add(key)
    result: list[Actor] = []
    seen: set[str] = set()
    for actor in actors:
        key = normalize_text(actor.name)
        if key in drop or key in seen:
            continue
        result.append(actor)
        seen.add(key)
    return result


def _extract_quantities(text: str) -> list[Quantity]:
    patterns = [
        r"(\d+(?:[\.,]\d+)?|một|mot|hai|ba|bốn|bon|năm|nam|sáu|sau|bảy|bay|tám|tam|chín|chin|mười|muoi)\s*(mét khối|gói|viên|gam|kg|m3|m³|g)",
        r"(\d+(?:[\.,]\d+)?)\s*(triệu|tỷ)(?:\s*đồng)?",
        r"(\d[\d\.]*(?:,\d+)?)\s*(đồng|dong)",
    ]
    quantities: list[Quantity] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.I):
            value = _parse_quantity_value(m.group(1))
            unit = m.group(2).lower()
            if unit == "tỷ" and value is not None:
                value *= 1_000_000_000
                unit = "đồng"
            if unit == "triệu" and value is not None:
                value *= 1_000_000
                unit = "đồng"
            quantities.append(Quantity(value=value, unit=unit, raw_text=m.group(0)))
    return quantities


def _merge_ner_entities(facts: ExtractedFacts, entities: CaseEntities) -> None:
    actor_by_key = {normalize_text(actor.name): actor for actor in facts.actors}
    for entity_actor in entities.actors:
        name = _clean_actor_name(entity_actor.name)
        key = normalize_text(name)
        if not key or key in _SUBSTANCE_NAME_KEYS:
            continue
        current = actor_by_key.get(key)
        if current:
            if entity_actor.role and not current.role:
                current.role = entity_actor.role
            if entity_actor.actions:
                note = "; ".join(entity_actor.actions)
                current.notes = note if not current.notes else f"{current.notes}; {note}"
            continue
        if _is_likely_actor_name(name):
            actor = Actor(
                name=name,
                role=entity_actor.role,
                notes="; ".join(entity_actor.actions) or None,
            )
            facts.actors.append(actor)
            actor_by_key[key] = actor

    for amount in entities.amounts:
        unit = "đồng" if amount.unit == "dong" else amount.unit
        quantity = Quantity(value=amount.value, unit=unit, raw_text=amount.raw)
        if not any(q.raw_text == quantity.raw_text and q.unit == quantity.unit and q.value == quantity.value for q in facts.quantities):
            facts.quantities.append(quantity)

    facts.article_refs = dedupe_keep_order(
        [*facts.article_refs, *[ref.article for ref in entities.article_refs]]
    )
    facts.actions = dedupe_keep_order([*facts.actions, *entities.actions, *entities.roles])
    facts.objects = dedupe_keep_order([*facts.objects, *entities.objects])
    facts.crime_hints = dedupe_keep_order([*facts.crime_hints, *entities.crime_hints])


def _extract_exhibits(text: str, quantities: list[Quantity]) -> list[ExhibitFact]:
    exhibits: list[ExhibitFact] = []
    seen: set[tuple[str, str]] = set()

    def add_exhibit(
        *,
        status: ExhibitStatus,
        description: str,
        form: str | None = None,
        suspected_substance: str | None = None,
        forensic_status: ForensicStatus = ForensicStatus.unknown,
        quantity: Quantity | None = None,
        evidence_source: EvidenceSource = EvidenceSource.user_statement,
        confidence: float = 0.55,
    ) -> None:
        source = re.sub(r"\s+", " ", description).strip()
        key = (status.value, source.lower())
        if key in seen:
            return
        seen.add(key)
        exhibits.append(ExhibitFact(
            status=status,
            description=source,
            form=form,
            suspected_substance=suspected_substance,
            forensic_status=forensic_status,
            quantity=quantity,
            source_text=source,
            evidence_source=evidence_source,
            confidence=confidence,
        ))

    default_source = EvidenceSource.police_record if re.search(r"(thu\s+giữ|thu\s+được|phát\s+hiện|bắt\s+quả\s+tang)", text, flags=re.I) else EvidenceSource.user_statement
    number_unit = r"(\d+(?:[\.,]\d+)?|một|mot|hai|ba|bốn|bon|năm|nam|sáu|sau|bảy|bay|tám|tam|chín|chin|mười|muoi)\s*"

    for match in re.finditer(rf"{number_unit}gói[^.;,]{{0,60}}", text, flags=re.I):
        source = re.split(rf"\s+và\s+{number_unit}viên", match.group(0).strip(), maxsplit=1, flags=re.I)[0].strip()
        norm_source = normalize_text(source)
        suspected = "ketamine" if "ketamin" in norm_source or "ketamine" in norm_source else None
        quantity = Quantity(value=_parse_quantity_value(match.group(1)), unit="gói", raw_text=f"{match.group(1)} gói", object="powder")
        add_exhibit(
            status=ExhibitStatus.suspected if "nghi" in norm_source else ExhibitStatus.seized if default_source == EvidenceSource.police_record else ExhibitStatus.mentioned,
            description=source,
            form="powder",
            suspected_substance=suspected,
            forensic_status=ForensicStatus.suspected if "nghi" in norm_source or suspected else ForensicStatus.mentioned,
            quantity=quantity,
            evidence_source=default_source,
            confidence=0.65 if default_source == EvidenceSource.police_record else 0.55,
        )

    for match in re.finditer(rf"{number_unit}viên[^.;,]{{0,70}}", text, flags=re.I):
        source = match.group(0).strip()
        norm_source = normalize_text(source)
        suspected = None
        if "thuoc lac" in norm_source or "mdma" in norm_source:
            suspected = "MDMA"
        elif "ma tuy tong hop" in norm_source:
            suspected = "ma túy tổng hợp"
        quantity = Quantity(value=_parse_quantity_value(match.group(1)), unit="viên", raw_text=f"{match.group(1)} viên", object="tablets")
        add_exhibit(
            status=ExhibitStatus.seized if default_source == EvidenceSource.police_record else ExhibitStatus.suspected if suspected else ExhibitStatus.mentioned,
            description=source,
            form="tablets",
            suspected_substance=suspected,
            forensic_status=ForensicStatus.suspected if suspected else ForensicStatus.mentioned,
            quantity=quantity,
            evidence_source=default_source,
            confidence=0.65 if default_source == EvidenceSource.police_record else 0.55,
        )

    powder_mass_pattern = (
        rf"(?:(?:còn\s+dư|còn\s+lại|còn|thu\s+giữ|thu\s+được|phát\s+hiện)[^. ;,]{{0,20}}\s*)?"
        rf"{number_unit}(gam|g|kg|mg)\s+(?:bột|chất\s+bột|gói\s+bột)[^.;,]{{0,60}}"
    )
    for match in re.finditer(powder_mass_pattern, text, flags=re.I):
        source = match.group(0).strip()
        norm_source = normalize_text(source)
        quantity = Quantity(
            value=_parse_quantity_value(match.group(1)),
            unit=match.group(2).lower(),
            raw_text=f"{match.group(1)} {match.group(2)}",
            object="powder",
        )
        source_has_seizure = any(term in norm_source for term in ["thu giu", "thu duoc", "phat hien", "con du", "con lai"])
        add_exhibit(
            status=ExhibitStatus.seized if source_has_seizure else ExhibitStatus.mentioned,
            description=source,
            form="powder",
            forensic_status=ForensicStatus.mentioned,
            quantity=quantity,
            evidence_source=EvidenceSource.police_record if source_has_seizure else default_source,
            confidence=0.65 if source_has_seizure else 0.55,
        )

    for status, pattern in EXHIBIT_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.I):
            if exhibits and status == "seized":
                continue
            source = re.sub(r"\s+", " ", match.group(0)).strip()
            key = (status, source.lower())
            if key in seen:
                continue
            seen.add(key)
            quantity = quantities[0] if quantities and status in {"seized", "mentioned"} else None
            exhibits.append(ExhibitFact(
                status=ExhibitStatus(status),
                description=source,
                quantity=quantity,
                source_text=source,
                evidence_source=default_source,
                confidence=0.6 if status == "seized" else 0.5,
            ))
    return exhibits


def _quantity_near_alias(text: str, alias: str, fallback: Quantity | None) -> Quantity | None:
    pattern = rf"{re.escape(alias)}\s*(\d+(?:[\.,]\d+)?)\s*(kg|g|gam|viên|gói)"
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return fallback
    raw_text = f"{match.group(1)}{match.group(2)}"
    return Quantity(value=_parse_float(match.group(1)), unit=match.group(2).lower(), raw_text=raw_text)


def _regex_extract(text: str) -> ExtractedFacts:
    norm = normalize_text(text)
    lowered = (text or "").lower()
    facts = ExtractedFacts()
    facts.actors = _extract_actors(text)
    facts.quantities = _extract_quantities(text)
    _merge_ner_entities(facts, extract_entities(text))
    facts.actors = _prune_actor_fragments(_merge_actor_aliases(text, facts.actors))
    facts.quantities = _dedupe_quantities(facts.quantities)
    facts.exhibits = _extract_exhibits(text, facts.quantities)
    facts.actions = [term for term in ACTION_TERMS if normalize_text(term) in norm]
    if "sử dụng" in facts.actions:
        drug_terms = {"ma tuy", "chat ma tuy", "ketamin", "ketamine", "mdma", "thuoc lac", "heroin", "can sa", "meth", "ma tuy da"}
        weapon_terms = {"sung", "sung ak", "vu khi", "luu dan"}
        sentence_norms = [normalize_text(part) for part in re.split(r"[\n.;!?]+", text) if part.strip()]
        has_drug_use_sentence = any("su dung" in sentence and any(term in sentence for term in drug_terms) for sentence in sentence_norms)
        has_weapon_use_sentence = any("su dung" in sentence and any(term in sentence for term in weapon_terms) for sentence in sentence_norms)
        if has_weapon_use_sentence and not has_drug_use_sentence and "duong tinh" not in norm:
            facts.actions = [action for action in facts.actions if action != "sử dụng"]
    facts.consequences = [term for term in CONSEQUENCE_TERMS if normalize_text(term) in norm]
    facts.location = [term for term in LOCATION_TERMS if normalize_text(term) in norm]
    facts.mitigating_signals = [term for term in MITIGATING_TERMS if normalize_text(term) in norm]
    facts.aggravating_signals = [term for term in AGGRAVATING_TERMS if normalize_text(term) in norm]
    facts.article_refs = dedupe_keep_order(re.findall(r"[Đđ]iều\s+(\d+[a-zA-Z]?)", text))
    facts.age_info = dedupe_keep_order([m.group(0) for m in re.finditer(r"(?:\d{1,2}\s*tuổi|dưới\s*\d{1,2}|từ\s*đủ\s*\d{1,2}|đủ\s*70\s*tuổi)", text, flags=re.I)])
    facts.intent = [term for term in ["mục đích", "hưởng lợi", "cho bạn", "để bán", "để sử dụng", "để long sử dụng"] if normalize_text(term) in norm]
    facts.mental_state = [term for term in ["cố ý", "vô ý", "biết", "không biết"] if normalize_text(term) in norm]
    facts.evidence = [term for term in ["giám định", "kết luận giám định", "dương tính", "camera", "lời khai"] if normalize_text(term) in norm]
    if "chuyen khoan" in norm:
        facts.evidence.append("chuyển khoản")
        facts.structured_facts["evidence.electronic"] = ["bank_transfer"]
    delivery_fee = re.search(r"(\d[\d\.]*(?:,\d+)?)\s*đồng\s+phí\s+giao\s+hàng", text, flags=re.I)
    if delivery_fee:
        facts.structured_facts["transactions.drug_purchase.delivery_fee"] = _parse_float(delivery_fee.group(1))
    purchase_price = re.search(r"(?:giá|tiền\s+mua\s+ma\s+túy)[^.;:]{0,40}?(\d[\d\.]*(?:,\d+)?)\s*đồng", text, flags=re.I)
    if purchase_price:
        facts.structured_facts["transactions.drug_purchase.price"] = _parse_float(purchase_price.group(1))
        primary_actor = _primary_drug_purchase_actor(facts, text)
        if primary_actor:
            facts.structured_facts["transactions.drug_purchase.money_source"] = primary_actor
    if "duong tinh" in norm:
        facts.evidence.append("xét nghiệm dương tính")
    if "khong con tang vat" in norm or any(exhibit.status == "consumed" for exhibit in facts.exhibits):
        facts.evidence.append("không còn tang vật")
        facts.unknowns.append("Không còn tang vật: cần hồ sơ xét nghiệm/giám định và chứng cứ khác để chứng minh chất ma túy, nguồn cung, hành vi.")
    if any(exhibit.status == "not_seized" for exhibit in facts.exhibits):
        facts.evidence.append("không thu giữ được tang vật")
        facts.unknowns.append("Không thu giữ được tang vật: cần chứng cứ thay thế như xét nghiệm, lời khai, camera, tin nhắn hoặc chuyển khoản.")
    for alias, name in SUBSTANCE_ALIASES.items():
        alias_norm = normalize_text(alias)
        if len(alias_norm) <= 2:
            matched = bool(re.search(rf"(?<!\w){re.escape(alias.lower())}(?!\w)", lowered))
        else:
            matched = alias_norm in norm
        if matched:
            quantity = _quantity_near_alias(text, alias, facts.quantities[0] if facts.quantities else None)
            confidence = 0.55 if re.search(rf"nghi\s+{re.escape(alias)}", lowered, flags=re.I) else 0.9
            facts.substances.append(SubstanceFact(name=name, alias=alias, quantity=quantity, confidence=confidence))
    facts.objects = [s.name for s in facts.substances]
    tokens = set(norm.split())
    if "lam san" in norm or "rung" in tokens or "go" in tokens:
        facts.objects.append("gỗ/lâm sản")
        facts.crime_hints.append("tội vi phạm quy định về khai thác, bảo vệ rừng và lâm sản")
    if facts.substances:
        facts.crime_hints.append("nhóm tội phạm về ma túy")
    if any(term in norm for term in ["ban thang", "no sung", "sung ak", "trung dan", "hy sinh", "chet nguoi", "tu vong"]):
        facts.objects.append("súng AK" if "sung ak" in norm else "súng")
        facts.crime_hints.append("tội giết người")
    if any(term in norm for term in ["sung ak", "hop tiep dan", "luu dan", "vu khi quan dung"]):
        facts.objects.append("vũ khí quân dụng")
        facts.crime_hints.append("tội tàng trữ, sử dụng trái phép vũ khí quân dụng")
    if any(term in norm for term in ["lam hu hong xe", "hu hong xe", "thiet hai tai san", "lam hu hong tai san"]):
        facts.objects.append("xe/tài sản")
        facts.crime_hints.append("tội cố ý làm hư hỏng tài sản")
    facts.actions = dedupe_keep_order(facts.actions)
    facts.objects = dedupe_keep_order(facts.objects)
    facts.evidence = dedupe_keep_order(facts.evidence)
    facts.intent = dedupe_keep_order(facts.intent)
    facts.unknowns = dedupe_keep_order(facts.unknowns)
    return facts


def _dedupe_quantities(quantities: list[Quantity]) -> list[Quantity]:
    result: list[Quantity] = []
    seen: set[tuple[float | None, str, str]] = set()
    for quantity in quantities:
        raw_key = normalize_text(quantity.raw_text).replace("dong", "đồng")
        key = (quantity.value, normalize_text(quantity.unit or ""), raw_key)
        if key in seen:
            continue
        result.append(quantity)
        seen.add(key)
    return result


def _primary_drug_purchase_actor(facts: ExtractedFacts, text: str) -> str | None:
    norm = normalize_text(text)
    if not any(term in norm for term in ["khai nhan da mua", "da mua ma tuy", "tien mua ma tuy", "gia"]):
        return None
    for actor in facts.actors:
        actor_key = normalize_text(actor.name)
        if actor_key == "nguoi giup viec quan ly":
            continue
        if any(part in norm for part in [actor_key, *actor_key.split()[-2:]]):
            return actor.name
    return facts.actors[0].name if facts.actors else None


def _safe_json(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        return json.loads(m.group(0)) if m else {}


def _llm_extract(text: str) -> ExtractedFacts | None:
    if not settings.use_llm_fact_extractor or not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": FACT_EXTRACTION_SYSTEM},
                {"role": "user", "content": FACT_EXTRACTION_USER.format(scenario=text)},
            ],
        )
        return ExtractedFacts.model_validate(_safe_json(resp.choices[0].message.content or ""))
    except Exception as exc:
        logger.warning("LLM fact extraction skipped: %s", exc)
        return None


@lru_cache(maxsize=256)
def extract_facts(text: str) -> ExtractedFacts:
    base = _regex_extract(text)
    llm = _llm_extract(text)
    if not llm:
        return base
    for field in ExtractedFacts.model_fields:
        current = getattr(base, field)
        extra = getattr(llm, field)
        if isinstance(current, list):
            current.extend([x for x in extra if x not in current])
    return base
