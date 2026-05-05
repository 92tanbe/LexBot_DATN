"""Cross-encoder reranker (BAAI/bge-reranker-v2-m3) cho tieng Viet.

Su dung CrossEncoder cua sentence-transformers de score (query, chunk_text)
roi giu top_k.

Quan trong - Combined scoring:
    Reranker da-ngon-ngu chua phan biet tot nuance phap ly tieng Viet
    (vd: "giet" co y khac "vo y lam chet"). Vi vay ket qua cuoi cung
    KHONG dung rerank_score don le, ma KET HOP voi rrf_score theo cong thuc:

        final_score = (1 / (k + rank_rerank)) + (1 / (k + rank_rrf))

    Cong thuc nay (Reciprocal Rank Fusion 2 nguon) tan dung diem manh
    cua ca rerank (semantic) lan rrf (fulltext-aware). Khi rerank loi,
    rrf van keo dap an dung len cao.

Khi `combine_with_rrf=False`, dung rerank thuan; khi reranker khong
load duoc, fallback ve rrf_score.
"""
from __future__ import annotations

import logging
import threading
from typing import Iterable

from app.core.config import settings
from app.models.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


_reranker = None
_reranker_lock = threading.Lock()

# He so RRF ket hop 2 ranking (giong logic cua hybrid.py)
_COMBINE_RRF_K = 60


def _load_reranker():
    """Lazy load CrossEncoder."""
    global _reranker
    if _reranker is not None:
        return _reranker
    if not settings.enable_reranker:
        return None
    with _reranker_lock:
        if _reranker is not None:
            return _reranker
        try:
            from sentence_transformers import CrossEncoder

            logger.info("Load reranker model %s", settings.reranker_model)
            _reranker = CrossEncoder(
                settings.reranker_model,
                max_length=512,
                device=settings.embedding_device,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Khong load duoc reranker: %s", exc)
            _reranker = None
    return _reranker


def get_reranker():
    return _load_reranker()


def _truncate(text: str, max_chars: int = 1500) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + " ..."


def rerank(
    query: str,
    candidates: Iterable[RetrievedChunk],
    top_k: int | None = None,
    combine_with_rrf: bool = True,
) -> list[RetrievedChunk]:
    """Score lai cac candidate va sort.

    Args:
        query: cau hoi.
        candidates: chunks ung vien (da co rrf_score tu hybrid).
        top_k: gioi han ket qua tra ve.
        combine_with_rrf: True (mac dinh) -> ket hop rerank rank + rrf rank
            theo cong thuc Reciprocal Rank Fusion. False -> chi dung rerank thuan.
    """
    cands = list(candidates)
    if not cands:
        return []
    keep = top_k or settings.reranker_top_k

    # Ranking ban dau theo rrf (de combine sau)
    rrf_sorted = sorted(cands, key=lambda c: c.rrf_score, reverse=True)
    rrf_rank = {id(c): rank for rank, c in enumerate(rrf_sorted, start=1)}

    model = _load_reranker()
    if model is None:
        logger.debug("Reranker khong san sang, dung rrf_score lam fallback")
        for c in cands:
            c.rerank_score = c.rrf_score
            c.source = "rerank"
        cands.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return cands[:keep]

    pairs = [[query, _truncate(c.text)] for c in cands]
    try:
        scores = model.predict(pairs, batch_size=16, show_progress_bar=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Reranker predict loi: %s, fallback rrf", exc)
        for c in cands:
            c.rerank_score = c.rrf_score
            c.source = "rerank"
        cands.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return cands[:keep]

    for c, s in zip(cands, scores):
        c.rerank_score = float(s)
        c.source = "rerank"

    if not combine_with_rrf:
        cands.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return cands[:keep]

    # Ket hop 2 ranking bang RRF
    rerank_sorted = sorted(cands, key=lambda c: c.rerank_score or 0.0, reverse=True)
    rerank_rank = {id(c): rank for rank, c in enumerate(rerank_sorted, start=1)}

    def _combined(c: RetrievedChunk) -> float:
        return (1.0 / (_COMBINE_RRF_K + rerank_rank[id(c)])) + (
            1.0 / (_COMBINE_RRF_K + rrf_rank[id(c)])
        )

    cands.sort(key=_combined, reverse=True)
    # Luu vao meta de debug
    for c in cands:
        c.meta["combined_score"] = round(_combined(c), 5)
        c.meta["rrf_rank"] = rrf_rank[id(c)]
        c.meta["rerank_rank"] = rerank_rank[id(c)]
    return cands[:keep]
