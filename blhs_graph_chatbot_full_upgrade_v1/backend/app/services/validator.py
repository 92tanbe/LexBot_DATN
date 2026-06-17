from __future__ import annotations

import re

from app.models.legal_output import LegalReasoningItem

CERTAIN_PATTERNS = [
    r"\b[A-ZĐ]\s+phạm\s+tội\b",
    r"chắc chắn bị",
    r"sẽ bị phạt",
]


def validate_answer(final_answer: str, contexts: list[dict], missing: list[str], reasoning: list[LegalReasoningItem], confidence: float) -> tuple[str, float, list[str]]:
    warnings: list[str] = []
    supported = {str((ctx.get("article") or {}).get("article_code")) for ctx in contexts}
    for code in re.findall(r"Điều\s+(\d+[a-zA-Z]?)", final_answer):
        if code not in supported:
            warnings.append(f"LLM mentioned unsupported article: {code}")
            confidence *= 0.8
    if missing:
        if any(re.search(p, final_answer, flags=re.I) for p in CERTAIN_PATTERNS):
            warnings.append("Answer contained overly certain language while critical facts are missing.")
            final_answer += "\n\nLưu ý hiệu chỉnh: do còn thiếu dữ kiện, các nhận định trên chỉ nên hiểu là khả năng cần xem xét, chưa đủ căn cứ để kết luận chắc chắn."
            confidence *= 0.8
    general_only = all(item.classification == "general_rule" for item in reasoning) if reasoning else False
    if general_only:
        warnings.append("Only general rules were retrieved; do not treat them as main crime candidates.")
        confidence *= 0.7
    return final_answer, confidence, warnings
