"""Smoke test rieng cho vector index sau khi chay chunk_embed.

Cach chay:
    python -m chatbot.ingestion.verify_index --query "giet 2 nguoi"
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

from app.core.logging import setup_logging  # noqa: E402
from app.core.neo4j_driver import close_driver, session_scope  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.retrievers.embedding import embed_query  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="cướp tài sản giá trị 500 triệu")
    parser.add_argument("--top_k", type=int, default=5)
    args = parser.parse_args()

    setup_logging()
    q_emb = embed_query(args.query)

    cypher_dieu = """
    CALL db.index.vector.queryNodes($idx, $k, $emb) YIELD node, score
    RETURN node.article AS article, node.name AS name, score
    """
    cypher_rule = """
    CALL db.index.vector.queryNodes($idx, $k, $emb) YIELD node, score
    OPTIONAL MATCH (d:DieuLuat {crime_id: node.crime_id})
    RETURN d.article AS article, d.name AS dieu_name, node.rule_id AS rule_id,
           node.clause AS clause, score
    """

    try:
        with session_scope() as sess:
            print(f"\n=== Top {args.top_k} DieuLuat cho query: '{args.query}' ===")
            for r in sess.run(cypher_dieu, idx=settings.dieu_vector_index, k=args.top_k, emb=q_emb):
                print(f"  Dieu {r['article']:>3} | score={r['score']:.3f} | {r['name']}")

            print(f"\n=== Top {args.top_k} QuyTac cho query: '{args.query}' ===")
            for r in sess.run(cypher_rule, idx=settings.rule_vector_index, k=args.top_k, emb=q_emb):
                print(
                    f"  Dieu {r['article']:>3} khoan {r['clause']} | "
                    f"score={r['score']:.3f} | rule_id={r['rule_id']} | {r['dieu_name']}"
                )
    finally:
        close_driver()


if __name__ == "__main__":
    main()
