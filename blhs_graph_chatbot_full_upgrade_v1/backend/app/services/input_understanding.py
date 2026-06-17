from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.fast_response import detect_fast_response
from app.services.ner import extract_entities
from app.utils.text import dedupe_keep_order, normalize_text

logger = logging.getLogger(__name__)

InputScope = Literal[
    "empty",
    "greeting",
    "service_check",
    "thanks",
    "out_of_scope",
    "legal_other",
    "criminal_law",
    "unknown",
]


class SlangTerm(BaseModel):
    raw: str
    canonical: str
    category: str = "unknown"


class InputUnderstanding(BaseModel):
    scope: InputScope = "unknown"
    should_run_pipeline: bool = True
    quick_answer: str | None = None
    normalized_message: str
    actors: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    slang_terms: list[SlangTerm] = Field(default_factory=list)
    notes: str | None = None
    source: Literal["rule", "llm", "rule+llm"] = "rule"


_WEATHER_OR_CHITCHAT = [
    "thoi tiet",
    "hom nay mua khong",
    "nhiet do",
    "an gi",
    "nau an",
    "bong da",
    "the thao",
    "gia vang",
    "gia do la",
    "bitcoin",
]
_CRIMINAL_HINTS = [
    "blhs",
    "bo luat hinh su",
    "hinh su",
    "pham toi",
    "toi danh",
    "hinh phat",
    "khung hinh phat",
    "bi phat",
    "bi phat nhu the nao",
    "phat nhu the nao",
    "xu phat",
    "bi xu phat",
    "may nam tu",
    "bao nhieu nam tu",
    "di tu",
    "phat tu",
    "giet nguoi",
    "de doa giet nguoi",
    "ma tuy",
    "heroin",
    "ketamin",
    "ketamine",
    "thuoc lac",
    "tang tru",
    "van chuyen",
    "mua ban",
    "dang thong tin",
    "bia dat",
    "phat tan",
    "loan truyen",
    "danh du",
    "nhan pham",
    "cuop",
    "trom",
    "lua dao",
    "thuong tich",
    "chet nguoi",
    "tu vong",
    "dong pham",
]
_LEGAL_OTHER_HINTS = [
    "hop dong",
    "ly hon",
    "dat dai",
    "lao dong",
    "bao hiem",
    "thue",
    "doanh nghiep",
    "hanh chinh",
    "dan su",
]
_DECLINE_MORE_INFO = [
    "khong biet them",
    "khong ro them",
    "khong co thong tin them",
    "khong nam duoc",
    "toi khong biet",
]
_LOCATION_ALIASES = {
    "viet nam": "Việt Nam",
    "nuoc viet nam": "Việt Nam",
}
_SLANG_MAP = {
    "hang trang": SlangTerm(raw="hàng trắng", canonical="heroin", category="drug"),
    "heroin": SlangTerm(raw="heroin", canonical="heroin", category="drug"),
    "ma tuy da": SlangTerm(raw="ma túy đá", canonical="methamphetamine", category="drug"),
    "da": SlangTerm(raw="đá", canonical="methamphetamine", category="drug"),
    "ke": SlangTerm(raw="ke", canonical="ketamine", category="drug"),
    "ketamin": SlangTerm(raw="ketamin", canonical="ketamine", category="drug"),
    "ketamine": SlangTerm(raw="ketamine", canonical="ketamine", category="drug"),
    "keo": SlangTerm(raw="kẹo", canonical="MDMA", category="drug"),
    "thuoc lac": SlangTerm(raw="thuốc lắc", canonical="MDMA", category="drug"),
    "co": SlangTerm(raw="cỏ", canonical="cannabis", category="drug"),
    "can sa": SlangTerm(raw="cần sa", canonical="cannabis", category="drug"),
    "bay phong": SlangTerm(raw="bay phòng", canonical="sử dụng ma túy trong phòng", category="drug_context"),
}
_DIACRITIC_SENSITIVE_SLANG = {
    "da": r"(?<!\w)đá(?!\w)",
    "co": r"(?<!\w)cỏ(?!\w)",
}


def _contains_word(norm: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", norm))


def _detect_slang(message: str, norm: str) -> list[SlangTerm]:
    found: list[SlangTerm] = []
    seen: set[str] = set()
    lowered = (message or "").lower()
    for key, item in _SLANG_MAP.items():
        if key in _DIACRITIC_SENSITIVE_SLANG:
            matched = bool(re.search(_DIACRITIC_SENSITIVE_SLANG[key], lowered, flags=re.I))
        else:
            matched = _contains_word(norm, key) if len(key) <= 3 else key in norm
        if matched and item.canonical not in seen:
            found.append(item)
            seen.add(item.canonical)
    return found


def _detect_locations(norm: str) -> list[str]:
    locations: list[str] = []
    for key, label in _LOCATION_ALIASES.items():
        if key in norm:
            locations.append(label)
    return dedupe_keep_order(locations)


def _augment_with_slang(message: str, slang_terms: list[SlangTerm]) -> str:
    if not slang_terms:
        return message
    hints = "; ".join(f"{item.raw} = {item.canonical}" for item in slang_terms)
    return f"{message}\nNLP chuẩn hóa từ lóng: {hints}."


def _quick_answer(scope: InputScope) -> str | None:
    if scope == "greeting":
        return "Chào bạn, tôi có thể giúp gì cho bạn trong việc tham khảo Bộ luật Hình sự Việt Nam?"
    if scope == "service_check":
        return (
            "Tôi ở đây và đang hoạt động. Tôi có thể giúp bạn tra cứu điều luật "
            "hoặc phân tích tình huống theo Bộ luật Hình sự Việt Nam; bạn gửi tình huống cụ thể nhé."
        )
    if scope == "thanks":
        return "Không có gì. Nếu cần tra cứu hoặc phân tích tình huống theo BLHS, bạn cứ gửi tiếp."
    if scope == "empty":
        return "Bạn hãy nhập tình huống hoặc điều luật cần tham khảo trong phạm vi Bộ luật Hình sự Việt Nam."
    if scope == "out_of_scope":
        return (
            "Câu này chưa liên quan đến tư vấn Bộ luật Hình sự Việt Nam. "
            "Bạn cần tôi hỗ trợ tra cứu điều luật hoặc phân tích tình huống hình sự nào không?"
        )
    if scope == "legal_other":
        return (
            "Nội dung này có vẻ thuộc lĩnh vực pháp luật ngoài BLHS. "
            "Hiện tôi tập trung hỗ trợ Bộ luật Hình sự Việt Nam; bạn có tình huống hình sự cần phân tích không?"
        )
    return None


def _rule_understanding(message: str) -> InputUnderstanding:
    norm = normalize_text(message)
    fast = detect_fast_response(message)
    entities = extract_entities(message)
    slang_terms = _detect_slang(message, norm)
    locations = _detect_locations(norm)
    actors = [actor.name for actor in entities.actors]
    actions = dedupe_keep_order(entities.actions)

    scope: InputScope = "unknown"
    if any(term in norm for term in _DECLINE_MORE_INFO):
        scope = "unknown"
    elif fast and fast.get("kind") in {"empty", "greeting", "service_check", "thanks"}:
        scope = fast["kind"]
    elif any(_contains_word(norm, term) for term in _WEATHER_OR_CHITCHAT):
        scope = "out_of_scope"
    elif any(term in norm for term in _CRIMINAL_HINTS) or slang_terms:
        scope = "criminal_law"
    elif any(term in norm for term in _LEGAL_OTHER_HINTS):
        scope = "legal_other"
    elif fast and fast.get("kind") == "out_of_scope":
        scope = "out_of_scope"
    else:
        scope = "unknown"

    quick = _quick_answer(scope)
    return InputUnderstanding(
        scope=scope,
        should_run_pipeline=quick is None,
        quick_answer=quick,
        normalized_message=_augment_with_slang(message, slang_terms),
        actors=actors,
        locations=locations,
        actions=actions,
        slang_terms=slang_terms,
        source="rule",
    )


def _safe_json(raw: str) -> dict[str, Any]:
    value = (raw or "").strip()
    value = re.sub(r"^```[a-zA-Z]*", "", value).strip()
    value = re.sub(r"```$", "", value).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, flags=re.S)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


def _llm_understanding(message: str) -> InputUnderstanding | None:
    if not settings.use_llm_input_understanding or not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key, timeout=10.0)
        response = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Bạn phân loại đầu vào cho chatbot tư vấn Bộ luật Hình sự Việt Nam. "
                        "Không kết luận tội danh; chỉ phân loại scope, actor, địa danh, hành động, từ lóng và viết normalized_message. "
                        "Scope hợp lệ: empty, greeting, service_check, thanks, out_of_scope, legal_other, criminal_law, unknown. "
                        "Nếu người dùng chỉ chào, gọi thử, hỏi bot có hoạt động không, ping/test hệ thống, đặt should_run_pipeline=false "
                        "và trả quick_answer ngắn gọn rằng trợ lý đang ở đây để hỗ trợ. "
                        "Chỉ đặt criminal_law và should_run_pipeline=true khi có câu hỏi/tình huống hình sự hoặc BLHS."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Input: {message}\n"
                        "Trả JSON: {scope, should_run_pipeline, quick_answer, normalized_message, "
                        "actors[], locations[], actions[], slang_terms[{raw, canonical, category}], notes}."
                    ),
                },
            ],
        )
        data = _safe_json(response.choices[0].message.content or "")
        if not data:
            return None
        scope = data.get("scope")
        allowed_scopes = {
            "empty",
            "greeting",
            "service_check",
            "thanks",
            "out_of_scope",
            "legal_other",
            "criminal_law",
            "unknown",
        }
        if scope not in allowed_scopes:
            scope = "unknown"
        quick = data.get("quick_answer") or _quick_answer(scope)
        should_run_pipeline = bool(data.get("should_run_pipeline", quick is None))
        if scope in {"empty", "greeting", "service_check", "thanks", "out_of_scope", "legal_other"}:
            should_run_pipeline = False
            quick = quick or _quick_answer(scope)
        return InputUnderstanding.model_validate({
            **data,
            "scope": scope,
            "should_run_pipeline": should_run_pipeline,
            "quick_answer": quick if not should_run_pipeline else data.get("quick_answer"),
            "normalized_message": data.get("normalized_message") or message,
            "actors": data.get("actors") or [],
            "locations": data.get("locations") or [],
            "actions": data.get("actions") or [],
            "slang_terms": data.get("slang_terms") or [],
            "source": "llm",
        })
    except Exception as exc:
        logger.warning("LLM input understanding skipped: %s", exc)
        return None


def understand_input(message: str) -> InputUnderstanding:
    rule = _rule_understanding(message)
    llm = _llm_understanding(message)
    if not llm:
        return rule
    if rule.scope in {"empty", "greeting", "service_check", "thanks"}:
        return rule
    merged = llm.model_copy(
        update={
            "actors": dedupe_keep_order([*rule.actors, *llm.actors]),
            "locations": dedupe_keep_order([*rule.locations, *llm.locations]),
            "actions": dedupe_keep_order([*rule.actions, *llm.actions]),
            "slang_terms": [*rule.slang_terms, *llm.slang_terms],
            "normalized_message": llm.normalized_message or rule.normalized_message,
            "source": "rule+llm",
        }
    )
    if rule.scope == "out_of_scope":
        return merged if llm.scope != "unknown" else rule
    if rule.scope == "criminal_law" and llm.scope in {"out_of_scope", "legal_other", "unknown"}:
        return rule
    return merged
