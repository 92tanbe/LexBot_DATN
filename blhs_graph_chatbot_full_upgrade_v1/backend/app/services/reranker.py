from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)
_reranker = None


def _candidate_text(c: dict) -> str:
    parts = [c.get("title"), c.get("crime_name"), c.get("matched_text")]
    parts.extend(c.get("matched_terms") or [])
    return " ".join(str(p) for p in parts if p)


def warmup_reranker_model() -> bool:
    global _reranker
    if not settings.use_reranker:
        logger.info("Reranker warmup skipped because USE_RERANKER=false")
        return False
    try:
        from sentence_transformers import CrossEncoder
        if _reranker is None:
            _reranker = CrossEncoder(settings.reranker_model)
        _reranker.predict([["Bộ luật Hình sự", "Điều luật hình sự"]])
        logger.info("Reranker model warmed up: %s", settings.reranker_model)
        return True
    except Exception as exc:
        logger.warning("Reranker warmup skipped: %s", exc)
        return False


def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    global _reranker
    if not settings.use_reranker or not candidates:
        return candidates[:top_k]
    try:
        from sentence_transformers import CrossEncoder
        if _reranker is None:
            _reranker = CrossEncoder(settings.reranker_model)
        pairs = [[query, _candidate_text(c)] for c in candidates]
        scores = _reranker.predict(pairs)
        for c, score in zip(candidates, scores):
            c["rerank_score"] = float(score)
        rerank_sorted = sorted(candidates, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        rerank_rank = {c["article_code"]: i for i, c in enumerate(rerank_sorted, start=1)}
        rrf_rank = {c["article_code"]: i for i, c in enumerate(candidates, start=1)}
        for c in candidates:
            c["score"] = 1 / (60 + rerank_rank[c["article_code"]]) + 1 / (60 + rrf_rank[c["article_code"]])
            c["source"] = f"{c.get('source', '')}+rerank"
        return sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)[:top_k]
    except Exception as exc:
        logger.warning("Reranker skipped: %s", exc)
        return candidates[:top_k]
