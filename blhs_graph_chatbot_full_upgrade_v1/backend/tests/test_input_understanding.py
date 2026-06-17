from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.conversation import CaseStatus
from app.services.dialogue_manager import handle_legal_chat
from app.services.fact_extractor import extract_facts
from app.services.input_understanding import InputUnderstanding, understand_input
from app.services.session_store import session_store


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch):
    session_store.clear()
    extract_facts.cache_clear()
    monkeypatch.setattr(settings, "use_llm_fact_extractor", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    yield
    session_store.clear()
    extract_facts.cache_clear()


def test_greeting_returns_fast_blhs_prompt_without_pipeline():
    response = handle_legal_chat("Xin chào", include_debug=True)

    assert response.status == CaseStatus.answered
    assert response.clarification is None
    assert response.clarifying_questions == []
    assert "Bộ luật Hình sự Việt Nam" in response.final_answer
    assert response.debug["input_understanding"]["scope"] == "greeting"


def test_service_check_returns_presence_answer_without_pipeline():
    response = handle_legal_chat("Alo alo", include_debug=True)

    assert response.status == CaseStatus.answered
    assert response.clarification is None
    assert response.clarifying_questions == []
    assert "đang hoạt động" in response.final_answer
    assert response.debug["input_understanding"]["scope"] == "service_check"
    assert response.debug["input_understanding"]["should_run_pipeline"] is False


def test_out_of_scope_weather_returns_redirect_to_blhs():
    response = handle_legal_chat("Hôm nay thời tiết ở Hà Nội thế nào?", include_debug=True)

    assert response.status == CaseStatus.answered
    assert response.clarifying_questions == []
    assert "chưa liên quan" in response.final_answer
    assert "Bộ luật Hình sự Việt Nam" in response.final_answer
    assert response.debug["input_understanding"]["scope"] == "out_of_scope"


def test_llm_understanding_can_classify_short_probe(monkeypatch: pytest.MonkeyPatch):
    import app.services.input_understanding as input_understanding

    def fake_llm(message: str) -> InputUnderstanding:
        return InputUnderstanding(
            scope="service_check",
            should_run_pipeline=False,
            quick_answer="Tôi ở đây để giúp bạn.",
            normalized_message=message,
            source="llm",
        )

    monkeypatch.setattr(input_understanding, "_llm_understanding", fake_llm)

    understanding = input_understanding.understand_input("random probe")

    assert understanding.scope == "service_check"
    assert understanding.should_run_pipeline is False
    assert understanding.quick_answer == "Tôi ở đây để giúp bạn."
    assert understanding.source == "rule+llm"


def test_rule_understanding_detects_slang_location_and_no_fake_actor():
    understanding = understand_input("Vận chuyển 50 gram hàng trắng vào Việt Nam bị xử như thế nào?")

    assert understanding.scope == "criminal_law"
    assert "Việt Nam" in understanding.locations
    assert "Việt" not in understanding.actors
    assert any(term.canonical == "heroin" for term in understanding.slang_terms)
    assert "heroin" in understanding.normalized_message


def test_short_slang_does_not_match_common_words_after_accent_normalization():
    understanding = understand_input("Tôi đã có thông tin về hợp đồng.")

    assert {term.raw for term in understanding.slang_terms}.isdisjoint({"đá", "cỏ"})
    assert understanding.scope == "legal_other"


def test_legal_input_runs_pipeline_with_understanding_debug():
    response = handle_legal_chat(
        "Đăng thông tin bịa đặt gây ảnh hưởng tới danh dự người khác thì bị xử lý thế nào?",
        include_debug=True,
    )

    assert response.status in {CaseStatus.collecting_facts, CaseStatus.answered, CaseStatus.ready_to_answer}
    assert response.debug["input_understanding"]["scope"] == "criminal_law"
    assert "Đăng" not in {actor.name for actor in response.facts.actors}
    assert "đăng" in response.facts.actions


def test_general_murder_penalty_question_is_criminal_law():
    understanding = understand_input("tội giết người đi mấy năm tù")

    assert understanding.scope == "criminal_law"
    assert understanding.should_run_pipeline is True
