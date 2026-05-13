"""Test cho cac module retrieval (vector / fulltext / graph / hybrid)."""
from __future__ import annotations

import pytest

from app.models.schemas import RetrievedChunk
from app.retrievers.fulltext import sanitize_lucene_query
from app.retrievers.hybrid import reciprocal_rank_fusion


def test_sanitize_lucene_basic():
    assert sanitize_lucene_query("cuop tai san") == "cuop tai san"
    out = sanitize_lucene_query("cuop (vu khi) [du]")
    assert "(" not in out and ")" not in out


def test_sanitize_lucene_strip_specials():
    out = sanitize_lucene_query('cuop & "tai san"')
    assert '"' not in out


def _chunk(rule_id, score=1.0, source="vector", level="khoan", article=None, clause=None):
    return RetrievedChunk(
        source=source,
        level=level,
        text=f"chunk {rule_id}",
        score=score,
        article=article,
        clause=clause,
        rule_id=rule_id,
    )


def test_rrf_basic():
    a = _chunk("R1")
    b = _chunk("R2")
    c = _chunk("R3")
    ranking_1 = [a, b, c]
    ranking_2 = [b, a, c]
    fused = reciprocal_rank_fusion([ranking_1, ranking_2], k=60)
    ids = [c.rule_id for c in fused]
    # R1, R2 phai dung dau (vi xuat hien o vi tri cao trong ca 2 ranking)
    assert ids[0] in {"R1", "R2"}
    assert "R3" in ids


def test_rrf_dedup_provenance_merge():
    a1 = _chunk("R1", source="vector")
    a2 = _chunk("R1", source="graph", article=168, clause=1)
    fused = reciprocal_rank_fusion([[a1], [a2]], k=60)
    assert len(fused) == 1
    chunk = fused[0]
    assert chunk.article == 168 and chunk.clause == 1


def test_rrf_top_k():
    chunks = [_chunk(f"R{i}") for i in range(20)]
    fused = reciprocal_rank_fusion([chunks], k=60, top_k=5)
    assert len(fused) == 5


@pytest.mark.integration
def test_vector_search_dieu_optional(has_neo4j):
    if not has_neo4j:
        pytest.skip("Khong ket noi Neo4j")
    from app.retrievers.vector import search_dieu

    out = search_dieu("cuop tai san", top_k=3)
    # Co the empty neu vector index chua tao - chap nhan, miễn không exception
    assert isinstance(out, list)
