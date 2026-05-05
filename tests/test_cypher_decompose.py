"""Test cypher generator + decomposer."""
from __future__ import annotations

from app.nlp.cypher_gen import (
    ALLOWED_LABELS,
    is_safe_cypher,
    generate_candidates,
)
from app.nlp.decomposer import decompose
from app.nlp.ner import (
    Actor,
    ArticleRef,
    CaseEntities,
)


def test_is_safe_cypher_passes():
    cypher = "MATCH (d:DieuLuat) WHERE d.article = 168 RETURN d"
    ok, msg = is_safe_cypher(cypher)
    assert ok, msg


def test_is_safe_cypher_blocks_create():
    ok, msg = is_safe_cypher("MATCH (d:DieuLuat) CREATE (n:Bad) RETURN n")
    assert not ok


def test_is_safe_cypher_blocks_unknown_label():
    ok, msg = is_safe_cypher("MATCH (n:UserSecret) RETURN n")
    assert not ok


def test_is_safe_cypher_allows_whitelist():
    for label in ALLOWED_LABELS:
        cypher = f"MATCH (n:{label}) RETURN n LIMIT 1"
        ok, _ = is_safe_cypher(cypher)
        assert ok, f"Label {label} bi block!"


def test_generate_candidates_with_article_ref():
    ent = CaseEntities(article_refs=[ArticleRef(article=168, clause=2)])
    cands = generate_candidates("xem dieu 168 khoan 2", ent)
    names = {c.name for c in cands}
    assert "by_article" in names
    assert "lien_quan" in names


def test_decompose_no_actor():
    ent = CaseEntities()
    sub = decompose("Toi cuop tai san", ent)
    assert len(sub) == 1
    assert sub[0].is_overall


def test_decompose_two_actors():
    ent = CaseEntities(
        actors=[
            Actor(name="A", vai_tro="chinh pham", hanh_vi=["dung dao cuop"]),
            Actor(name="B", vai_tro="giup suc", hanh_vi=["canh gac"]),
        ],
        crime_hints=["toi cuop tai san"],
        actions=["cuop tai san"],
    )
    sub = decompose("A va B cung cuop", ent)
    # Co 2 actor + 1 overall = 3 sub-query
    assert len(sub) >= 3
    names = [s.actor_name for s in sub if s.actor_name]
    assert "A" in names and "B" in names
