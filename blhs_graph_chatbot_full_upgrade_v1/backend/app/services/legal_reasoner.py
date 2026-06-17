from __future__ import annotations

from app.models.facts import ExtractedFacts
from app.models.legal_output import LegalReasoningItem
from app.services.legal_matcher import score_context

SUPPORTING = {"8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "51", "52", "53", "54", "57", "58"}


def classify_context(ctx: dict) -> str:
    article = ctx.get("article") or {}
    code = str(article.get("article_code") or "")
    title = str(article.get("title") or "")
    if code in SUPPORTING:
        return "supporting_rule"
    if code in {"18", "19"}:
        return "crime_candidate"
    if ctx.get("crime") and title.lower().startswith("tội"):
        return "crime_candidate"
    return "general_rule"


def reason_over_contexts(contexts: list[dict], facts: ExtractedFacts, normalized: list[dict], missing: list[str]) -> list[LegalReasoningItem]:
    items: list[LegalReasoningItem] = []
    for ctx in contexts:
        article = ctx.get("article") or {}
        crime = ctx.get("crime") or {}
        score, matched = score_context(ctx, facts, normalized, missing)
        classification = classify_context(ctx)
        if missing and classification == "crime_candidate":
            finding_status = "insufficient_evidence"
        elif missing:
            finding_status = "possible_hypothesis"
        elif score >= 0.72 and classification == "crime_candidate":
            finding_status = "supported_conclusion"
        else:
            finding_status = "provisional_finding"
        warnings: list[str] = []
        if str(article.get("article_code")) in {"51", "52"}:
            warnings.append("Điều 51/52 là quy định về tình tiết, không phải tội danh chính.")
        items.append(LegalReasoningItem(
            article_code=str(article.get("article_code")),
            title=str(article.get("title")),
            crime_name=crime.get("name"),
            classification=classification,
            finding_status=finding_status,
            why_relevant="Khớp dữ kiện/tín hiệu truy vấn từ tình huống và graph Neo4j.",
            matched_elements=matched,
            missing_elements=missing,
            possible_penalty_frames=ctx.get("penalty_frames") or [],
            warnings=warnings,
            confidence=score,
        ))
    return sorted(items, key=lambda x: x.confidence, reverse=True)
