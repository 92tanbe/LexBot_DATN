"""Health & readiness probes."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.core.config import settings
from app.core.neo4j_driver import get_driver

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health")
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/readyz")
def ready() -> dict:
    """Readiness: kiem tra Neo4j + tra ve cau hinh chinh."""
    info: dict = {
        "neo4j": "unknown",
        "embedding_model": settings.embedding_model,
        "reranker_enabled": settings.enable_reranker,
        "openai_configured": bool(settings.openai_api_key),
        "env_file": settings.env_file_path,
    }
    try:
        drv = get_driver()
        drv.verify_connectivity()
        info["neo4j"] = "ok"
    except Exception as exc:  # noqa: BLE001
        info["neo4j"] = f"error: {exc}"
    return info
