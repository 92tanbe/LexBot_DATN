from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from neo4j import GraphDatabase, Query
from neo4j.graph import Node

from app.core.config import settings

logger = logging.getLogger(__name__)


def node_to_dict(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Node):
        data = dict(value)
        data["_labels"] = list(value.labels)
        data["_element_id"] = value.element_id
        return data
    if isinstance(value, list):
        return [node_to_dict(v) for v in value if v is not None]
    if isinstance(value, dict):
        return {k: node_to_dict(v) for k, v in value.items()}
    return value


class Neo4jDB:
    def __init__(self) -> None:
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            connection_timeout=settings.neo4j_connection_timeout,
            connection_acquisition_timeout=settings.neo4j_connection_timeout,
        )

    def close(self) -> None:
        self.driver.close()

    def verify(self) -> bool:
        with self.driver.session(database=settings.neo4j_database) as session:
            session.run(Query("RETURN 1 AS ok", timeout=settings.neo4j_query_timeout)).consume()
        return True

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        try:
            with self.driver.session(database=settings.neo4j_database) as session:
                result = session.run(Query(cypher, timeout=settings.neo4j_query_timeout), params or {})
                return [{k: node_to_dict(v) for k, v in dict(row).items()} for row in result]
        except Exception as exc:
            logger.exception("Neo4j query failed")
            raise HTTPException(status_code=503, detail=f"Neo4j query failed: {exc}") from exc

    def try_query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        try:
            return self.query(cypher, params)
        except HTTPException:
            return []

    def count_labels(self, labels: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for label in labels:
            rows = self.query(f"MATCH (n:{label}) RETURN count(n) AS count")
            counts[label] = int(rows[0]["count"]) if rows else 0
        return counts

    def ensure_indexes(self) -> None:
        statements = [
            "CREATE FULLTEXT INDEX article_fulltext IF NOT EXISTS FOR (a:Article) ON EACH [a.title, a.full_text]",
            "CREATE FULLTEXT INDEX condition_fulltext IF NOT EXISTS FOR (c:Condition) ON EACH [c.text]",
            "CREATE FULLTEXT INDEX crime_fulltext IF NOT EXISTS FOR (c:Crime) ON EACH [c.name]",
        ]
        with self.driver.session(database=settings.neo4j_database) as session:
            for statement in statements:
                try:
                    session.run(Query(statement, timeout=settings.neo4j_query_timeout)).consume()
                except Exception as exc:
                    logger.warning("Could not ensure index: %s", exc)


neo4j_db = Neo4jDB()
