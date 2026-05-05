"""Quan ly Neo4j driver dang singleton + helper chay query an toan."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterable

from neo4j import GraphDatabase, Driver, Session

from app.core.config import settings

logger = logging.getLogger(__name__)

_driver: Driver | None = None


def get_driver() -> Driver:
    """Tra ve singleton driver. Lazy init de tranh load khi import."""
    global _driver
    if _driver is None:
        logger.info("Khoi tao Neo4j driver tai %s", settings.neo4j_uri)
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        try:
            _driver.verify_connectivity()
        except Exception as exc:  # noqa: BLE001
            logger.warning("verify_connectivity that bai: %s", exc)
    return _driver


def close_driver() -> None:
    """Dong driver khi shutdown."""
    global _driver
    if _driver is not None:
        try:
            _driver.close()
        finally:
            _driver = None
            logger.info("Neo4j driver da dong")


@contextmanager
def session_scope() -> Iterable[Session]:
    """Context manager goi session ngan gon."""
    drv = get_driver()
    sess = drv.session(database=settings.neo4j_database) if settings.neo4j_database else drv.session()
    try:
        yield sess
    finally:
        sess.close()


def run_query(cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Chay 1 cypher read va tra ve list[dict]."""
    params = params or {}
    with session_scope() as sess:
        result = sess.run(cypher, **params)
        return [record.data() for record in result]
