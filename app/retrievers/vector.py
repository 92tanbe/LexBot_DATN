"""Vector search tren Neo4j vector index.

2 muc:
- DieuLuat (coarse, top_k_dieu)
- QuyTac   (fine,   top_k_khoan)
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.neo4j_driver import session_scope
from app.models.schemas import RetrievedChunk
from app.retrievers.embedding import embed_query

logger = logging.getLogger(__name__)


VECTOR_DIEU_QUERY = """
CALL db.index.vector.queryNodes($index, $top_k, $query_emb)
YIELD node AS d, score
OPTIONAL MATCH (d)<-[:CO_DIEU]-(c:Chuong)
OPTIONAL MATCH (c)-[:THUOC_NHOM]->(n:NhomToi)
RETURN d.crime_id   AS crime_id,
       d.article    AS article,
       d.name       AS dieu_name,
       d.chunk_text AS text,
       c.name       AS chuong,
       n.ten        AS nhom_toi,
       score
ORDER BY score DESC
"""


VECTOR_RULE_QUERY = """
CALL db.index.vector.queryNodes($index, $top_k, $query_emb)
YIELD node AS r, score
OPTIONAL MATCH (d:DieuLuat {crime_id: r.crime_id})
OPTIONAL MATCH (d)<-[:CO_DIEU]-(c:Chuong)
OPTIONAL MATCH (c)-[:THUOC_NHOM]->(n:NhomToi)
RETURN r.rule_id    AS rule_id,
       r.crime_id   AS crime_id,
       r.clause     AS clause,
       r.logic      AS logic,
       r.chunk_text AS text,
       d.article    AS article,
       d.name       AS dieu_name,
       c.name       AS chuong,
       n.ten        AS nhom_toi,
       score
ORDER BY score DESC
"""


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def search_dieu(query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    """Vector search muc DieuLuat."""
    k = top_k or settings.top_k_dieu
    emb = embed_query(query)

    with session_scope() as sess:
        try:
            records = sess.run(
                VECTOR_DIEU_QUERY,
                index=settings.dieu_vector_index,
                top_k=k,
                query_emb=emb,
            ).data()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vector search Dieu loi: %s", exc)
            return []

    chunks: list[RetrievedChunk] = []
    for r in records:
        text = r.get("text") or f"Dieu {r.get('article')}. {r.get('dieu_name') or ''}"
        chunks.append(
            RetrievedChunk(
                source="vector",
                level="dieu",
                text=text,
                score=float(r.get("score") or 0.0),
                article=_to_int_or_none(r.get("article")),
                crime_id=str(r["crime_id"]) if r.get("crime_id") is not None else None,
                dieu_name=r.get("dieu_name"),
                chuong=r.get("chuong"),
                nhom_toi=r.get("nhom_toi"),
            )
        )
    return chunks


def search_khoan(query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    """Vector search muc QuyTac (Khoan)."""
    k = top_k or settings.top_k_khoan
    emb = embed_query(query)

    with session_scope() as sess:
        try:
            records = sess.run(
                VECTOR_RULE_QUERY,
                index=settings.rule_vector_index,
                top_k=k,
                query_emb=emb,
            ).data()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vector search Khoan loi: %s", exc)
            return []

    chunks: list[RetrievedChunk] = []
    for r in records:
        text = r.get("text") or f"Dieu {r.get('article')} khoan {r.get('clause')}"
        chunks.append(
            RetrievedChunk(
                source="vector",
                level="khoan",
                text=text,
                score=float(r.get("score") or 0.0),
                article=_to_int_or_none(r.get("article")),
                clause=_to_int_or_none(r.get("clause")),
                rule_id=r.get("rule_id"),
                crime_id=str(r["crime_id"]) if r.get("crime_id") is not None else None,
                dieu_name=r.get("dieu_name"),
                chuong=r.get("chuong"),
                nhom_toi=r.get("nhom_toi"),
                logic=r.get("logic"),
            )
        )
    return chunks
