"""Hybrid retrieval ket hop vector + fulltext + graph qua RRF.

RRF (Reciprocal Rank Fusion):
    score(d) = sum_i ( 1 / (k + rank_i(d)) )

Co loc trung lap qua key:
    - Voi level=khoan: dung rule_id
    - Voi level=dieu: dung crime_id + dieu_name
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Iterable

from app.core.config import settings
from app.models.schemas import RetrievedChunk
from app.retrievers import vector as vec_retriever
from app.retrievers import fulltext as ft_retriever
from app.retrievers import graph as graph_retriever

logger = logging.getLogger(__name__)


def _chunk_key(c: RetrievedChunk) -> str:
    """Tao khoa de loc trung."""
    if c.rule_id:
        return f"rule::{c.rule_id}"
    if c.crime_id:
        return f"crime::{c.crime_id}::{c.level}"
    return f"text::{hash(c.text)}"


def reciprocal_rank_fusion(
    rankings: list[list[RetrievedChunk]],
    k: int | None = None,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Hop nhat nhieu ranking thanh 1 ranking duy nhat.

    Args:
        rankings: list cac danh sach da sap xep theo do quan trong giam dan.
        k: hang so RRF (mac dinh 60).
        top_k: gioi han so chunk tra ve.
    """
    rrf_k = k if k is not None else settings.rrf_k
    fused: dict[str, RetrievedChunk] = {}
    score_acc: dict[str, float] = defaultdict(float)

    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            key = _chunk_key(chunk)
            score_acc[key] += 1.0 / (rrf_k + rank)
            if key not in fused:
                fused[key] = chunk
            else:
                fused[key].merge_provenance(chunk)
                # Giu source uu tien graph > vector > fulltext
                priority = {"graph": 3, "vector": 2, "fulltext": 1, "rrf": 0, "rerank": 0}
                if priority.get(chunk.source, 0) > priority.get(fused[key].source, 0):
                    fused[key].source = chunk.source

    items = []
    for key, chunk in fused.items():
        chunk.rrf_score = score_acc[key]
        chunk.source = "rrf"
        items.append(chunk)

    items.sort(key=lambda c: c.rrf_score, reverse=True)
    if top_k:
        items = items[:top_k]
    return items


# ---------------------------------------------------------------------------


def retrieve_for_query(
    query: str,
    fulltext_keywords: Iterable[str] | None = None,
    article_refs: Iterable[tuple[int, int | None]] | None = None,
    role_hints: Iterable[str] | None = None,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Hybrid retrieval cho 1 query.

    Args:
        query: cau hoi hoac sub-query da chuan hoa.
        fulltext_keywords: tu khoa rieng cho fulltext (vd: ten toi, action).
        article_refs: list (article, clause|None) lay tu NER de truy thang graph.
        role_hints: list vai tro (chu muu, dong pham, ...) de truy graph theo VaiTro.
        top_k: gioi han chunk sau RRF (truoc rerank).

    Returns:
        list[RetrievedChunk] sau RRF, da sort theo rrf_score giam dan.
    """
    rankings: list[list[RetrievedChunk]] = []

    # 1. Vector search 2 muc
    rankings.append(vec_retriever.search_khoan(query))
    rankings.append(vec_retriever.search_dieu(query))

    # 2. Fulltext (uu tien tu khoa explicit)
    keywords = list(fulltext_keywords or [])
    if not keywords:
        keywords = [query]
    for kw in keywords[:3]:  # han che de tranh noisy
        rankings.append(ft_retriever.search_dieu_by_name(kw))
        rankings.append(ft_retriever.search_dieu_kien(kw))

    # 3. Graph traversal theo article_refs
    for ref in (article_refs or []):
        try:
            article, clause = ref
        except (TypeError, ValueError):
            continue
        if article is None:
            continue
        if clause is not None:
            rankings.append(graph_retriever.fetch_by_article_clause(article, clause))
        else:
            rankings.append(graph_retriever.fetch_by_article(article))
        # Mo rong them lien quan
        rankings.append(graph_retriever.fetch_lien_quan(article))

    # 4. Graph theo role
    for role in (role_hints or []):
        if role:
            rankings.append(graph_retriever.fetch_by_role(role))

    # Bo cac ranking rong de RRF khong nhieu
    rankings = [r for r in rankings if r]
    if not rankings:
        return []

    fused = reciprocal_rank_fusion(rankings, top_k=top_k or settings.candidate_top_k)
    logger.debug("RRF fuse %d sources -> %d chunks", len(rankings), len(fused))
    return fused
