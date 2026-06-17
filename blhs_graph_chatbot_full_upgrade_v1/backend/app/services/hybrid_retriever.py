from __future__ import annotations

from app.core.config import settings
from app.models.facts import ExtractedFacts
from app.services.fulltext_retriever import fallback_contains, search_conditions, search_fulltext
from app.services.graph_retriever import search_articles_by_title_terms, search_exact_articles, search_related_from_signals
from app.services.rrf import reciprocal_rank_fusion
from app.services.vector_retriever import vector_search


def retrieve_candidates(
    query_items: list[dict],
    facts: ExtractedFacts,
    normalized: list[dict],
    top_k: int,
) -> tuple[list[dict], dict]:
    rankings: list[list[dict]] = []
    debug: dict = {"query_items": query_items, "sources": {}}
    exact = search_exact_articles(facts.article_refs, top_k)
    if exact:
        rankings.append(exact)
        debug["sources"]["exact_article"] = len(exact)
    signal = search_related_from_signals(normalized, top_k)
    if signal:
        rankings.append(signal)
        debug["sources"]["normalized_signal_graph"] = len(signal)
    action_norms = {" ".join(a.lower().split()) for a in facts.actions}
    title_terms: list[str] = []
    if facts.substances:
        if "tổ chức sử dụng" in action_norms:
            title_terms.append("tổ chức sử dụng trái phép chất ma túy")
        if "sử dụng" in action_norms:
            title_terms.append("sử dụng trái phép chất ma túy")
        if "mua" in action_norms or "mua bán" in action_norms:
            title_terms.append("mua bán trái phép chất ma túy")
            title_terms.append("tàng trữ trái phép chất ma túy")
    title_hits = search_articles_by_title_terms(title_terms, top_k)
    if title_hits:
        title_priority: dict[str, float] = {}
        if "tổ chức sử dụng" in action_norms:
            title_priority["255"] = 2.2
        if "mua" in action_norms or "mua bán" in action_norms:
            title_priority["251"] = 2.1
            title_priority["249"] = 1.8
        if "sử dụng" in action_norms:
            title_priority["256a"] = 1.9
            title_priority["256"] = 1.5
        for hit in title_hits:
            code = str(hit.get("article_code"))
            if code in title_priority:
                hit["score"] = title_priority[code]
                hit["source"] = f"{hit.get('source')}+action_boost"
        title_hits = sorted(title_hits, key=lambda h: float(h.get("score") or 0.0), reverse=True)
        rankings.append(title_hits)
        debug["sources"]["legal_action_title"] = len(title_hits)
    for item in query_items[:12]:
        q = item["text"]
        ft = search_fulltext(q, top_k)
        cond = search_conditions(q, top_k)
        vec = vector_search(q, top_k) if settings.use_vector_search else []
        if ft:
            rankings.append(ft)
        if cond:
            rankings.append(cond)
        if vec:
            rankings.append(vec)
    if not rankings:
        rankings.append(fallback_contains(query_items[0]["text"], top_k))
    fused = reciprocal_rank_fusion(rankings, k=settings.rrf_k)
    if title_hits:
        priority_codes = {str(hit.get("article_code")): idx for idx, hit in enumerate(title_hits) if float(hit.get("score") or 0.0) >= 1.8}
        fused = sorted(fused, key=lambda item: (priority_codes.get(str(item.get("article_code")), 999), -float(item.get("score") or 0.0)))
    fused = fused[:top_k]
    debug["ranking_count"] = len(rankings)
    debug["fused_count"] = len(fused)
    return fused, debug
