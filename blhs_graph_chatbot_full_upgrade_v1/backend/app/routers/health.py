from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Request

from app.core.config import settings
from app.core.neo4j import neo4j_db

router = APIRouter(tags=["health"])


def _neo4j_uri_hint() -> str:
    try:
        return urlparse(settings.neo4j_uri).hostname or ""
    except Exception:
        return ""


@router.get("/health")
def health(request: Request) -> dict:
    labels = ["Article", "Crime", "Clause", "Point", "Condition", "Rule", "PenaltyFrame", "Penalty"]
    base = {
        "service": "blhs-graph-v2",
        "neo4j_uri_hint": _neo4j_uri_hint(),
        "neo4j_database": settings.neo4j_database,
        "warmup_status": getattr(request.app.state, "warmup_status", {}),
    }
    try:
        counts = neo4j_db.count_labels(labels)
        return {
            **base,
            "status": "ok",
            "neo4j_connected": True,
            "database_counts": counts,
        }
    except Exception as exc:
        return {
            **base,
            "status": "error",
            "neo4j_connected": False,
            "database_counts": {},
            "error": str(exc),
        }
