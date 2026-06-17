from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.fact_extractor import extract_facts
from app.services.ner import extract_amounts, extract_article_refs, extract_entities


@pytest.fixture(autouse=True)
def no_llm(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "use_llm_fact_extractor", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    extract_facts.cache_clear()
    yield
    extract_facts.cache_clear()


def test_extract_article_refs_basic_and_clause_first():
    refs = extract_article_refs("Theo Điều 168 khoản 2 và khoản 1 Điều 173 BLHS.")

    assert any(ref.article == "168" and ref.clause == "2" for ref in refs)
    assert any(ref.article == "173" and ref.clause == "1" for ref in refs)


def test_extract_amounts_money_percent_and_people():
    amounts = extract_amounts("Chiếm đoạt 2 tỷ đồng, thương tích 35%, có 3 người.")
    units = {amount.unit for amount in amounts}

    assert "dong" in units
    assert "percent" in units
    assert "nguoi" in units
    assert any(amount.value == 2_000_000_000 for amount in amounts)


def test_extract_entities_finds_actors_roles_actions_and_objects_without_llm():
    entities = extract_entities(
        "Long nhờ Tân đặt phòng karaoke qua Thuận để Long sử dụng ma túy."
    )
    names = {actor.name for actor in entities.actors}
    roles = {actor.name: actor.role for actor in entities.actors}

    assert {"Long", "Tân", "Thuận"} <= names
    assert roles["Long"] == "người nhờ/khởi xướng"
    assert roles["Tân"] == "người được nhờ"
    assert "đặt phòng" in entities.actions
    assert "ma túy" in entities.objects


def test_fact_extractor_merges_ner_entities_into_facts():
    facts = extract_facts("Long nhờ Tân đặt phòng karaoke qua Thuận để Long sử dụng ma túy.")
    roles = {actor.name: actor.role for actor in facts.actors}

    assert {"Long", "Tân", "Thuận"} <= {actor.name for actor in facts.actors}
    assert roles["Long"] == "người nhờ/khởi xướng"
    assert roles["Tân"] == "người được nhờ"
    assert "đặt phòng" in facts.actions


def test_viet_nam_location_is_not_actor():
    text = "Vận chuyển 50 gram heroin vào Việt Nam bị xử như thế nào?"
    entities = extract_entities(text)
    facts = extract_facts(text)

    entity_names = {actor.name for actor in entities.actors}
    fact_names = {actor.name for actor in facts.actors}
    assert "Việt" not in entity_names
    assert "Việt Nam" not in entity_names
    assert "Việt" not in fact_names
    assert "Việt Nam" not in fact_names
    assert "Việt Nam" in facts.location
    assert "vận chuyển" in facts.actions


def test_dang_information_is_action_not_actor():
    text = "Đăng thông tin bịa đặt gây ảnh hưởng tới danh dự và nhân phẩm người khác thì xử lý thế nào?"
    entities = extract_entities(text)
    facts = extract_facts(text)

    assert "Đăng" not in {actor.name for actor in entities.actors}
    assert "Đăng" not in {actor.name for actor in facts.actors}
    assert "đăng" in facts.actions
    assert "bịa đặt" in facts.actions
