"""Graph traversal Cypher templates - tra theo article/clause/role/nhom_toi.

Dung khi NER da trich duoc tham chieu cu the (vd: 'theo Dieu 168 khoan 2').
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.neo4j_driver import session_scope
from app.models.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


GRAPH_BY_ARTICLE_QUERY = """
MATCH (d:DieuLuat)
WHERE toInteger(d.article) = toInteger($article)
OPTIONAL MATCH (d)-[:CO_QUY_TAC]->(r:QuyTac)
OPTIONAL MATCH (d)<-[:CO_DIEU]-(c:Chuong)
OPTIONAL MATCH (c)-[:THUOC_NHOM]->(n:NhomToi)
RETURN d.crime_id   AS crime_id,
       d.article    AS article,
       d.name       AS dieu_name,
       d.chunk_text AS dieu_text,
       r.rule_id    AS rule_id,
       r.clause     AS clause,
       r.logic      AS logic,
       r.chunk_text AS rule_text,
       c.name       AS chuong,
       n.ten        AS nhom_toi
ORDER BY toInteger(coalesce(r.clause, 0)), r.priority
"""


GRAPH_BY_ARTICLE_CLAUSE_QUERY = """
MATCH (d:DieuLuat)-[:CO_QUY_TAC]->(r:QuyTac)
WHERE toInteger(d.article) = toInteger($article)
  AND toInteger(coalesce(r.clause, -1)) = toInteger($clause)
OPTIONAL MATCH (d)<-[:CO_DIEU]-(c:Chuong)
OPTIONAL MATCH (c)-[:THUOC_NHOM]->(n:NhomToi)
RETURN d.crime_id   AS crime_id,
       d.article    AS article,
       d.name       AS dieu_name,
       d.chunk_text AS dieu_text,
       r.rule_id    AS rule_id,
       r.clause     AS clause,
       r.logic      AS logic,
       r.chunk_text AS rule_text,
       c.name       AS chuong,
       n.ten        AS nhom_toi
ORDER BY r.priority
"""


GRAPH_BY_ROLE_QUERY = """
MATCH (v:VaiTro)
WHERE toLower(v.ten) CONTAINS toLower($role)
MATCH (dk:DieuKien)-[:LA_VAI_TRO]->(v)
MATCH (r:QuyTac {rule_id: dk.rule_id})
OPTIONAL MATCH (d:DieuLuat {crime_id: r.crime_id})
OPTIONAL MATCH (d)<-[:CO_DIEU]-(c:Chuong)
OPTIONAL MATCH (c)-[:THUOC_NHOM]->(n:NhomToi)
RETURN d.crime_id   AS crime_id,
       d.article    AS article,
       d.name       AS dieu_name,
       d.chunk_text AS dieu_text,
       r.rule_id    AS rule_id,
       r.clause     AS clause,
       r.logic      AS logic,
       r.chunk_text AS rule_text,
       c.name       AS chuong,
       n.ten        AS nhom_toi,
       v.ten        AS vai_tro
LIMIT 20
"""


GRAPH_LIEN_QUAN_QUERY = """
MATCH (d:DieuLuat)
WHERE toInteger(d.article) = toInteger($article)
MATCH (d)-[:LIEN_QUAN]->(d2:DieuLuat)
OPTIONAL MATCH (d2)<-[:CO_DIEU]-(c:Chuong)
RETURN d2.crime_id   AS crime_id,
       d2.article    AS article,
       d2.name       AS dieu_name,
       d2.chunk_text AS dieu_text,
       c.name        AS chuong
LIMIT 10
"""


def _to_int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _build_chunk_from_record(r: dict, prefer_rule: bool = True) -> RetrievedChunk:
    text = r.get("rule_text") if prefer_rule else r.get("dieu_text")
    if not text:
        text = r.get("dieu_text") or r.get("rule_text") or ""
    if not text:
        text = f"Dieu {r.get('article')} khoan {r.get('clause')}".strip()

    return RetrievedChunk(
        source="graph",
        level="khoan" if r.get("rule_id") else "dieu",
        text=text,
        score=1.0,
        article=_to_int_or_none(r.get("article")),
        clause=_to_int_or_none(r.get("clause")),
        rule_id=r.get("rule_id"),
        crime_id=str(r["crime_id"]) if r.get("crime_id") is not None else None,
        dieu_name=r.get("dieu_name"),
        chuong=r.get("chuong"),
        nhom_toi=r.get("nhom_toi"),
        logic=r.get("logic"),
    )


def fetch_by_article(article: int) -> list[RetrievedChunk]:
    """Lay tat ca khoan cua 1 dieu luat."""
    with session_scope() as sess:
        records = sess.run(GRAPH_BY_ARTICLE_QUERY, article=int(article)).data()
    return [_build_chunk_from_record(r) for r in records if r]


def fetch_by_article_clause(article: int, clause: int) -> list[RetrievedChunk]:
    """Lay 1 khoan cu the."""
    with session_scope() as sess:
        records = sess.run(
            GRAPH_BY_ARTICLE_CLAUSE_QUERY, article=int(article), clause=int(clause)
        ).data()
    return [_build_chunk_from_record(r) for r in records if r]


def fetch_by_role(role: str) -> list[RetrievedChunk]:
    """Tim cac quy tac co vai tro/dong pham match keyword."""
    role = (role or "").strip()
    if not role:
        return []
    with session_scope() as sess:
        records = sess.run(GRAPH_BY_ROLE_QUERY, role=role).data()
    return [_build_chunk_from_record(r) for r in records if r]


def fetch_lien_quan(article: int) -> list[RetrievedChunk]:
    """Lay cac dieu luat duoc LIEN_QUAN tu mot dieu."""
    with session_scope() as sess:
        records = sess.run(GRAPH_LIEN_QUAN_QUERY, article=int(article)).data()
    return [_build_chunk_from_record(r, prefer_rule=False) for r in records if r]
