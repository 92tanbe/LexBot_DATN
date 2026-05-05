"""Smoke test pipeline e2e (integration)."""
from __future__ import annotations

import pytest


@pytest.mark.integration
def test_pipeline_smoke(has_neo4j):
    if not has_neo4j:
        pytest.skip("Khong ket noi Neo4j")
    from app.pipeline.orchestrator import run_pipeline

    resp = run_pipeline(
        question="Toi cuop tai san 100 trieu thi bi xu phat the nao?",
        top_k=5,
        include_debug=True,
    )
    assert resp.final_answer
    assert resp.confidence in {"high", "medium", "low"}
    assert isinstance(resp.citations, list)


@pytest.mark.integration
def test_pipeline_decompose_multi_actor(has_neo4j, has_openai):
    if not has_neo4j:
        pytest.skip("Khong ket noi Neo4j")
    if not has_openai:
        pytest.skip("Khong co OPENAI_API_KEY")
    from app.pipeline.orchestrator import run_pipeline

    resp = run_pipeline(
        question="A va B cung cuop, A dung dao, B canh gac. Hinh phat cho A va B la gi?",
        top_k=8,
        include_debug=True,
    )
    assert resp.debug is not None
    # Phai co >= 2 sub-query
    assert len(resp.debug.sub_queries) >= 2
