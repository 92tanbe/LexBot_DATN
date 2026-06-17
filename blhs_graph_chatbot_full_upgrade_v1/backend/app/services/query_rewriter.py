from __future__ import annotations

from app.models.facts import ExtractedFacts
from app.services.decomposer import SubQuery
from app.utils.text import dedupe_keep_order


def rewrite_queries(scenario: str, facts: ExtractedFacts, sub_queries: list[SubQuery], normalized: list[dict]) -> list[dict]:
    queries: list[dict] = [{"text": scenario, "source": "original", "is_hyde": False}]
    if facts.actions:
        queries.append({"text": " ".join(facts.actions + facts.objects), "source": "action_based", "is_hyde": False})
    for sq in sub_queries:
        queries.append({"text": sq.text, "source": "actor_specific" if sq.actor_name else "overall", "is_hyde": False})
    for hint in facts.crime_hints:
        queries.append({"text": hint, "source": "crime_hint", "is_hyde": False})
    for ref in facts.article_refs:
        queries.append({"text": f"Điều {ref}", "source": "article_ref", "is_hyde": False})
    for sub in facts.substances:
        queries.append({"text": sub.name, "source": "substance", "is_hyde": False})
    for item in normalized:
        for key in ("target_name", "signal_name", "substance_name"):
            if item.get(key):
                queries.append({"text": item[key], "source": "slang_normalized", "is_hyde": False})
    if facts.quantities:
        queries.append({"text": " ".join(q.raw_text for q in facts.quantities), "source": "quantity_threshold", "is_hyde": False})
    if facts.substances or facts.quantities:
        queries.append({"text": f"Tình huống pháp lý giả định: {scenario}. Cần đối chiếu hành vi, chủ thể, vật chứng, kết luận giám định, định lượng và khung hình phạt trong BLHS.", "source": "hyde_rule", "is_hyde": True})
    seen = dedupe_keep_order([q["text"] for q in queries])
    return [q for q in queries if q["text"] in seen]
