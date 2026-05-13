"""Pytest fixtures: them path va check ket noi Neo4j."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHATBOT_ROOT = Path(__file__).resolve().parents[1]
for _p in (_CHATBOT_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture(scope="session")
def has_neo4j() -> bool:
    """Tra ve True neu Neo4j ket noi duoc, dung de skip test phu thuoc."""
    try:
        from app.core.neo4j_driver import get_driver

        get_driver().verify_connectivity()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def has_openai() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))
