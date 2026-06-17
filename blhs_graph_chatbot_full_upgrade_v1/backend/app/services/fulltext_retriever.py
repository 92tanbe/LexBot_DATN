from __future__ import annotations

import logging
import re

from app.core.neo4j import neo4j_db

logger = logging.getLogger(__name__)


def sanitize_lucene_query(q: str) -> str:
    cleaned = re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', " ", q or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or q


def _fulltext(index: str, q: str, limit: int) -> list[dict]:
    q = sanitize_lucene_query(q)
    try:
        return neo4j_db.query(
            f"""
            CALL db.index.fulltext.queryNodes('{index}', $q) YIELD node, score
            OPTIONAL MATCH (node)<-[:DEFINES_CRIME]-(a1:Article)
            WITH node, score, coalesce(a1, node) AS a
            WHERE a:Article
            RETURN a.article_code AS article_code, a.title AS title,
                   CASE WHEN node:Crime THEN node.name ELSE null END AS crime_name,
                   score AS score, $index AS source, [coalesce(node.name, node.title, node.text)] AS matched_terms
            ORDER BY score DESC LIMIT $limit
            """,
            {"q": q, "limit": limit, "index": index},
        )
    except Exception as exc:
        logger.warning("Fulltext index %s unavailable: %s", index, exc)
        return []


def search_fulltext(q: str, limit: int = 10) -> list[dict]:
    rows: list[dict] = []
    rows.extend(_fulltext("article_fulltext", q, limit))
    rows.extend(_fulltext("crime_fulltext", q, limit))
    rows.extend(_fulltext("condition_fulltext", q, limit))
    if rows:
        return rows[:limit]
    return fallback_contains(q, limit)


def fallback_contains(q: str, limit: int = 10) -> list[dict]:
    rows: list[dict] = []
    rows.extend(neo4j_db.try_query(
        """
        MATCH (a:Article)
        WHERE toLower(a.title) CONTAINS toLower($q)
           OR toLower(a.full_text) CONTAINS toLower($q)
        RETURN a.article_code AS article_code, a.title AS title, 1.0 AS score,
               "article_contains" AS source, [$q] AS matched_terms
        LIMIT $limit
        """,
        {"q": q, "limit": limit},
    ))
    rows.extend(neo4j_db.try_query(
        """
        MATCH (a:Article)-[:DEFINES_CRIME]->(c:Crime)
        WHERE toLower(c.name) CONTAINS toLower($q)
           OR toLower(a.title) CONTAINS toLower($q)
        RETURN a.article_code AS article_code, a.title AS title, c.name AS crime_name,
               1.2 AS score, "crime_title" AS source, [c.name] AS matched_terms
        LIMIT $limit
        """,
        {"q": q, "limit": limit},
    ))
    return rows[:limit]


def search_conditions(q: str, limit: int = 10) -> list[dict]:
    return neo4j_db.try_query(
        """
        MATCH (a:Article)-[:HAS_CLAUSE]->(cl:Clause)
        OPTIONAL MATCH (cl)-[:HAS_POINT]->(pt:Point)
        OPTIONAL MATCH (cl)-[:HAS_CONDITION]->(c1:Condition)
        OPTIONAL MATCH (pt)-[:HAS_CONDITION]->(c2:Condition)
        WITH a, cl, collect(c1) + collect(c2) AS conds
        UNWIND conds AS cond
        WITH a, cl, cond
        WHERE cond IS NOT NULL AND toLower(cond.text) CONTAINS toLower($q)
        RETURN DISTINCT a.article_code AS article_code, a.title AS title, cl.clause_no AS clause_no,
               cond.text AS matched_text, 1.1 AS score, "condition_contains" AS source,
               [cond.text] AS matched_terms
        LIMIT $limit
        """,
        {"q": q, "limit": limit},
    )
