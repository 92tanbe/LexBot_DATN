"""Fulltext search tren cac index Neo4j da co san trong notebook import.

Index co san:
- dieu_name_search    : DieuLuat.name
- dk_text_search      : DieuKien.text
"""
from __future__ import annotations

import logging
import re

from app.core.config import settings
from app.core.neo4j_driver import session_scope
from app.models.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


FULLTEXT_DIEU_QUERY = """
CALL db.index.fulltext.queryNodes('dieu_name_search', $keyword)
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
LIMIT $top_k
"""


FULLTEXT_DK_QUERY = """
CALL db.index.fulltext.queryNodes('dk_text_search', $keyword)
YIELD node AS dk, score
MATCH (r:QuyTac {rule_id: dk.rule_id})
OPTIONAL MATCH (d:DieuLuat {crime_id: r.crime_id})
OPTIONAL MATCH (d)<-[:CO_DIEU]-(c:Chuong)
OPTIONAL MATCH (c)-[:THUOC_NHOM]->(n:NhomToi)
RETURN r.rule_id    AS rule_id,
       r.crime_id   AS crime_id,
       r.clause     AS clause,
       r.logic      AS logic,
       r.chunk_text AS text,
       dk.text      AS dk_text,
       d.article    AS article,
       d.name       AS dieu_name,
       c.name       AS chuong,
       n.ten        AS nhom_toi,
       score
ORDER BY score DESC
LIMIT $top_k
"""


_FT_RESERVED = re.compile(r'([+\-!(){}\[\]\^"~*?:\\\/]|&&|\|\|)')


def sanitize_lucene_query(text: str) -> str:
    """Escape ky tu dac biet cua Lucene de tranh loi syntax."""
    text = (text or "").strip()
    if not text:
        return ""
    text = _FT_RESERVED.sub(r" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _to_int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def search_dieu_by_name(keyword: str, top_k: int | None = None) -> list[RetrievedChunk]:
    """Fulltext theo ten toi danh."""
    keyword = sanitize_lucene_query(keyword)
    if not keyword:
        return []
    k = top_k or settings.top_k_fulltext
    with session_scope() as sess:
        try:
            records = sess.run(FULLTEXT_DIEU_QUERY, keyword=keyword, top_k=k).data()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fulltext dieu_name_search loi: %s", exc)
            return []

    chunks: list[RetrievedChunk] = []
    for r in records:
        text = r.get("text") or f"Dieu {r.get('article')}. {r.get('dieu_name') or ''}"
        chunks.append(
            RetrievedChunk(
                source="fulltext",
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


def search_dieu_kien(keyword: str, top_k: int | None = None) -> list[RetrievedChunk]:
    """Fulltext theo noi dung dieu kien (truy ve QuyTac chua dieu kien do)."""
    keyword = sanitize_lucene_query(keyword)
    if not keyword:
        return []
    k = top_k or settings.top_k_fulltext
    with session_scope() as sess:
        try:
            records = sess.run(FULLTEXT_DK_QUERY, keyword=keyword, top_k=k).data()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fulltext dk_text_search loi: %s", exc)
            return []

    chunks: list[RetrievedChunk] = []
    for r in records:
        text = r.get("text") or r.get("dk_text") or ""
        if not text and r.get("article"):
            text = f"Dieu {r['article']} khoan {r.get('clause')}"
        chunks.append(
            RetrievedChunk(
                source="fulltext",
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
                meta={"matched_dk": r.get("dk_text")},
            )
        )
    return chunks
