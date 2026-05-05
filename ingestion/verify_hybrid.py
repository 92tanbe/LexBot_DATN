"""Smoke test hybrid retrieval (vector + fulltext + RRF + rerank).

Khong can OpenAI / NER / Cypher gen — chi check 4 lop retrieval co bi sung lan nhau khong.

Cach chay:
    python -m ingestion.verify_hybrid --query "giet 2 nguoi"
    python -m ingestion.verify_hybrid --query "tham o 1 ty" --no-rerank
    python -m ingestion.verify_hybrid --query "đồng phạm cướp" --top_k 8
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHATBOT_ROOT = Path(__file__).resolve().parents[1]
for _p in (_CHATBOT_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.core.config import settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.core.neo4j_driver import close_driver  # noqa: E402
from app.retrievers import fulltext as ft_ret  # noqa: E402
from app.retrievers import vector as vec_ret  # noqa: E402
from app.retrievers.hybrid import reciprocal_rank_fusion, retrieve_for_query  # noqa: E402

logger = logging.getLogger(__name__)


def _print_chunks(title: str, chunks, limit: int = 5) -> None:
    print(f"\n=== {title} (top {min(limit, len(chunks))}/{len(chunks)}) ===")
    for i, c in enumerate(chunks[:limit], start=1):
        sc_parts = []
        combined = c.meta.get("combined_score") if c.meta else None
        if combined is not None:
            sc_parts.append(f"combined={combined:.5f}")
        if getattr(c, "rerank_score", None) is not None:
            sc_parts.append(f"rerank={c.rerank_score:.3f}")
        if c.rrf_score:
            sc_parts.append(f"rrf={c.rrf_score:.4f}")
        if c.score:
            sc_parts.append(f"raw={c.score:.3f}")
        score_str = " | ".join(sc_parts) or "-"
        head = f"  [{i}] "
        if c.article is not None:
            head += f"Dieu {c.article}"
        if c.clause is not None:
            head += f" khoan {c.clause}"
        if c.rule_id:
            head += f" ({c.rule_id})"
        print(f"{head} | {score_str}")
        if c.dieu_name:
            print(f"      {c.dieu_name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--top_k", type=int, default=8)
    parser.add_argument("--no-rerank", action="store_true", help="Bo qua reranker, chi xem RRF")
    args = parser.parse_args()

    setup_logging()
    print(f"\n## Query: {args.query!r}")

    try:
        # 1. Tung lop retrieval rieng le
        v_dieu = vec_ret.search_dieu(args.query, top_k=settings.top_k_dieu)
        _print_chunks("Vector - DieuLuat", v_dieu)

        v_khoan = vec_ret.search_khoan(args.query, top_k=settings.top_k_khoan)
        _print_chunks("Vector - QuyTac (Khoan)", v_khoan)

        ft_name = ft_ret.search_dieu_by_name(args.query, top_k=settings.top_k_fulltext)
        _print_chunks("Fulltext - dieu_name_search", ft_name)

        ft_dk = ft_ret.search_dieu_kien(args.query, top_k=settings.top_k_fulltext)
        _print_chunks("Fulltext - dk_text_search (DieuKien)", ft_dk)

        # 2. RRF fuse
        fused = reciprocal_rank_fusion(
            [v_dieu, v_khoan, ft_name, ft_dk],
            top_k=settings.candidate_top_k,
        )
        _print_chunks("Hybrid RRF (truoc rerank)", fused, limit=args.top_k)

        # 3. Rerank (optional)
        if not args.no_rerank and fused:
            from app.retrievers.reranker import rerank as rerank_fn

            reranked = rerank_fn(args.query, fused, top_k=args.top_k)
            _print_chunks("Hybrid + Rerank (cuoi cung)", reranked, limit=args.top_k)
        else:
            print("\n(Bo qua rerank)")

        # 4. Cung cap full retrieve_for_query (giong orchestrator)
        full = retrieve_for_query(query=args.query, top_k=settings.candidate_top_k)
        _print_chunks("retrieve_for_query() (orchestrator)", full, limit=args.top_k)
    finally:
        close_driver()


if __name__ == "__main__":
    main()
