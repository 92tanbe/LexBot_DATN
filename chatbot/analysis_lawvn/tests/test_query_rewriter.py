"""Test multi-query rewriting + HyDE."""
from __future__ import annotations

from app.nlp.decomposer import decompose
from app.nlp.ner import Actor, Amount, ArticleRef, CaseEntities
from app.nlp.query_rewriter import rewrite_queries


def test_rewrite_queries_adds_hyde_amount_and_additional_penalty():
    entities = CaseEntities(
        actors=[
            Actor(name="A", vai_tro="chinh pham", hanh_vi=["dung hung khi cuop tiem vang"]),
            Actor(name="B", vai_tro="dong pham", hanh_vi=["cho A bo tron"]),
        ],
        roles=["chinh pham", "dong pham"],
        actions=["cuop tai san"],
        amounts=[Amount(value=1_000_000_000, unit="dong", raw="1 ty")],
        article_refs=[ArticleRef(article=168)],
        crime_hints=["toi cuop tai san"],
    )
    sub_queries = decompose("A va B cuop tiem vang hon 1 ty", entities)

    rewritten = rewrite_queries(
        "A va B cuop tiem vang hon 1 ty",
        entities,
        sub_queries,
        max_queries=8,
        enable_llm_hyde=False,
    )

    texts = [q.text for q in rewritten]
    joined = "\n".join(texts)

    assert any(q.is_hyde for q in rewritten)
    assert "500.000.000" in joined
    assert "Hình phạt bổ sung Điều 168" in joined
    assert any(q.source == "sub_query" and q.actor_name == "A" for q in rewritten)


def test_rewrite_queries_dedup_and_respects_limit():
    entities = CaseEntities(
        article_refs=[ArticleRef(article=168)],
        crime_hints=["toi cuop tai san"],
    )
    sub_queries = decompose("toi cuop tai san", entities)

    rewritten = rewrite_queries(
        "toi cuop tai san",
        entities,
        sub_queries,
        max_queries=4,
        enable_llm_hyde=False,
    )

    normalized = [q.text.lower().strip() for q in rewritten]
    assert len(rewritten) == 4
    assert len(normalized) == len(set(normalized))
    assert any(q.is_hyde for q in rewritten)


def test_rewrite_queries_medical_negligence_prefers_article_129():
    entities = CaseEntities(
        actors=[
            Actor(name="E", vai_tro="chinh pham", hanh_vi=["boc nham thuoc"]),
            Actor(name="F", vai_tro="nan nhan", hanh_vi=["tu vong"]),
        ],
        actions=["ke thuoc", "boc nham thuoc"],
        objects=["thuoc chua benh", "benh nhan tu vong"],
    )
    question = "Bac si E ke thuoc nhung boc nham thuoc cho chi F, sau khi uong F tu vong"
    sub_queries = decompose(question, entities)

    rewritten = rewrite_queries(question, entities, sub_queries, max_queries=12, enable_llm_hyde=False)
    joined = "\n".join(q.text for q in rewritten)

    assert "Điều 129" in joined
    assert "không phải ma túy" in joined
    assert any(q.is_hyde and "Điều 129" in q.text for q in rewritten)
