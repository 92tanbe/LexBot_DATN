"""Test NER pipeline (regex + underthesea + LLM hybrid)."""
from __future__ import annotations

import pytest

from app.nlp.ner import (
    extract_amounts,
    extract_article_refs,
)


def test_extract_article_refs_basic():
    refs = extract_article_refs("Theo Dieu 168 khoan 2 BLHS thi nguoi do se bi xu ly")
    assert any(r.article == 168 and r.clause == 2 for r in refs)


def test_extract_article_refs_multiple():
    refs = extract_article_refs("Can xem Dieu 17 va Dieu 168 khoan 1 cua BLHS")
    arts = {r.article for r in refs}
    assert 17 in arts and 168 in arts


def test_extract_article_refs_clause_first():
    refs = extract_article_refs("khoan 2 Dieu 173")
    assert any(r.article == 173 and r.clause == 2 for r in refs)


def test_extract_amounts_money():
    amts = extract_amounts("Toi cuop 500 trieu va danh nhau gay thuong tich 35%")
    units = {a.unit for a in amts}
    assert "dong" in units
    assert "percent" in units


def test_extract_amounts_billion():
    amts = extract_amounts("Tham o 2 ty dong nha nuoc")
    money = next((a for a in amts if a.unit == "dong"), None)
    assert money is not None
    assert money.value == 2_000_000_000


def test_extract_amounts_people():
    amts = extract_amounts("Giet 2 nguoi va lam bi thuong 3 nguoi")
    nguoi = [a for a in amts if a.unit == "nguoi"]
    assert len(nguoi) >= 1


@pytest.mark.skip(reason="Goi LLM thuc te - bat trong CI khi co OPENAI key")
def test_extract_entities_with_llm(has_openai):
    if not has_openai:
        pytest.skip("Khong co OPENAI_API_KEY")
    from app.nlp.ner import extract_entities

    ent = extract_entities("A va B cung cuop xe may, A dung dao, B canh gac")
    assert len(ent.actors) >= 2
