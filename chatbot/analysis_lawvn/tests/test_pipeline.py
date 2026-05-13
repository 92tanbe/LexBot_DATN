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


def test_boost_additional_penalty_chunks(monkeypatch):
    from app.models.schemas import RetrievedChunk
    from app.pipeline import orchestrator

    base = RetrievedChunk(
        source="rrf",
        level="khoan",
        text="Dieu 168 khoan 2",
        rrf_score=0.05,
        article=168,
        clause=2,
        rule_id="168_r2",
        logic="AGGRAVATION",
    )
    additional = RetrievedChunk(
        source="graph",
        level="khoan",
        text="Dieu 168 khoan 6. Hinh phat bo sung: phat tien, quan che, cam cu tru.",
        article=168,
        clause=6,
        rule_id="168_r6",
        logic="ADDITIONAL_PENALTY",
    )

    monkeypatch.setattr(
        orchestrator.graph_retriever,
        "fetch_by_article",
        lambda article: [base, additional],
    )

    boosted = orchestrator._boost_additional_penalty_chunks([base])

    assert [c.rule_id for c in boosted] == ["168_r6"]
    assert boosted[0].meta["domain_boost"] == "additional_penalty"


def test_boost_amount_threshold_chunks_for_large_amount(monkeypatch):
    from app.models.schemas import RetrievedChunk
    from app.nlp.ner import Amount, CaseEntities
    from app.pipeline import orchestrator

    base = RetrievedChunk(
        source="rrf",
        level="khoan",
        text="Dieu 168 khoan 2",
        rrf_score=0.05,
        article=168,
        clause=2,
        rule_id="168_r2",
        logic="AGGRAVATION",
    )
    clause_4 = RetrievedChunk(
        source="graph",
        level="khoan",
        text="Chiếm đoạt tài sản trị giá 500.000.000 đồng trở lên. Hình phạt: phạt tù từ 18 đến 20 năm.",
        article=168,
        clause=4,
        rule_id="168_r4",
        logic="AGGRAVATION",
    )

    monkeypatch.setattr(
        orchestrator.graph_retriever,
        "fetch_by_article",
        lambda article: [base, clause_4],
    )

    entities = CaseEntities(amounts=[Amount(value=1_000_000_000, unit="dong", raw="1 tỷ")])
    boosted = orchestrator._boost_amount_threshold_chunks(entities, [base])

    assert [c.rule_id for c in boosted] == ["168_r4"]
    assert boosted[0].meta["domain_boost"] == "amount_threshold"


def test_apply_additional_penalties_adds_extra_and_citation():
    from app.models.legal_output import ActorAnalysis, CaseAnalysis, HinhPhatOutput, ToiDanhOutput
    from app.models.schemas import RetrievedChunk
    from app.pipeline import orchestrator

    case = CaseAnalysis(
        summary="A cuop tai san",
        actors=[
            ActorAnalysis(
                name="A",
                vai_tro="chinh pham",
                toi_danh=[
                    ToiDanhOutput(
                        dieu=168,
                        khoan=4,
                        ten_toi="Toi cuop tai san",
                        vai_tro="chinh pham",
                        hinh_phat=HinhPhatOutput(loai="tu", min=18, max=20, don_vi="nam"),
                    )
                ],
            )
        ],
        confidence="high",
    )
    additional = RetrievedChunk(
        source="graph",
        level="khoan",
        text=(
            "Dieu 168 khoan 6 - Toi cuop tai san\n"
            "Hinh phat: Co the bi phat tien tu 10.000.000 dong den 100.000.000 dong."
        ),
        article=168,
        clause=6,
        rule_id="168_r6",
        logic="ADDITIONAL_PENALTY",
    )

    enriched = orchestrator._apply_additional_penalties(case, [additional])
    td = enriched.actors[0].toi_danh[0]

    assert "Hình phạt bổ sung" in (td.hinh_phat.extra or "")
    assert any(c.rule_id == "168_r6" for c in td.citations)


def test_boost_medical_negligence_chunks_prefers_article_129(monkeypatch):
    from app.models.schemas import RetrievedChunk
    from app.nlp.ner import Actor, CaseEntities
    from app.pipeline import orchestrator

    article_129 = RetrievedChunk(
        source="graph",
        level="khoan",
        text="Điều 129 khoản 1 - Vô ý làm chết người do vi phạm quy tắc nghề nghiệp.",
        article=129,
        clause=1,
        rule_id="129_r1",
        logic="BASE",
    )
    article_128 = RetrievedChunk(
        source="graph",
        level="khoan",
        text="Điều 128 khoản 1 - Vô ý làm chết người.",
        article=128,
        clause=1,
        rule_id="128_r1",
        logic="BASE",
    )

    def fake_fetch(article):
        return {129: [article_129], 128: [article_128]}.get(article, [])

    monkeypatch.setattr(orchestrator.graph_retriever, "fetch_by_article", fake_fetch)
    entities = CaseEntities(
        actors=[
            Actor(name="E", vai_tro="chinh pham", hanh_vi=["boc nham thuoc"]),
            Actor(name="F", vai_tro="nan nhan", hanh_vi=["tu vong"]),
        ],
        actions=["ke thuoc", "boc nham thuoc"],
        objects=["thuoc chua benh"],
    )

    chunks = orchestrator._boost_medical_negligence_chunks(
        "Bac si E kham benh, ke thuoc nhung boc nham thuoc lam F tu vong",
        entities,
    )

    assert [c.rule_id for c in chunks] == ["129_r1", "128_r1"]
    assert chunks[0].rrf_score > chunks[1].rrf_score
    assert chunks[0].meta["domain_boost"] == "medical_negligence"
