from __future__ import annotations

import logging

from app.core.config import settings
from app.core.neo4j import neo4j_db

logger = logging.getLogger(__name__)
_model = None


def _embed(text: str) -> list[float] | None:
    global _model
    if not settings.use_vector_search:
        return None
    try:
        from sentence_transformers import SentenceTransformer
        if _model is None:
            _model = SentenceTransformer(settings.embedding_model, device=settings.embedding_device)
        return _model.encode(
            text,
            batch_size=settings.embedding_batch_size,
            normalize_embeddings=True,
        ).tolist()
    except Exception as exc:
        logger.warning("Vector embedding skipped: %s", exc)
        return None


def warmup_embedding_model() -> bool:
    if not settings.use_vector_search:
        logger.info("Vector warmup skipped because USE_VECTOR_SEARCH=false")
        return False
    emb = _embed("Bộ luật Hình sự")
    warmed = emb is not None
    if warmed:
        if len(emb) != settings.embedding_dim:
            logger.warning(
                "Embedding dimension mismatch: model returned %s, EMBEDDING_DIM=%s",
                len(emb),
                settings.embedding_dim,
            )
        logger.info("Vector embedding model warmed up: %s", settings.embedding_model)
    return warmed


def vector_search(query: str, limit: int = 10) -> list[dict]:
    emb = _embed(query)
    if emb is None:
        return []
    index_names = [r.get("name") for r in neo4j_db.try_query("SHOW INDEXES YIELD name, type WHERE type = 'VECTOR' RETURN name")]
    searches = [
        ("article_embedding", "Article"),
        ("clause_embedding", "Clause"),
        ("rule_embedding", "Rule"),
    ]
    rows: list[dict] = []
    for index, _label in searches:
        if index not in index_names:
            continue
        rows.extend(neo4j_db.try_query(
            f"""
            CALL db.index.vector.queryNodes('{index}', $limit, $embedding) YIELD node, score
            OPTIONAL MATCH (a:Article)-[:HAS_CLAUSE|HAS_RULE*0..2]->(node)
            WITH node, score, coalesce(a, node) AS article
            WHERE article:Article
            OPTIONAL MATCH (article)-[:DEFINES_CRIME]->(c:Crime)
            RETURN article.article_code AS article_code, article.title AS title, c.name AS crime_name,
                   score AS score, 'vector' AS source, [coalesce(node.title, node.text, node.name)] AS matched_terms
            LIMIT $limit
            """,
            {"embedding": emb, "limit": limit},
        ))
    return rows[:limit]
