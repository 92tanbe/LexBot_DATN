from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models.agentic import AgenticChatRequest
from app.services.agentic_rag_service import extract_legal_facts, run_agentic_rag
from app.services.conversation_state import conversation_state_store


def test_agentic_fact_extraction_drug_examples():
    _, facts = extract_legal_facts("Tàng trữ 2g ma túy đá thì bị phạt bao nhiêu?")
    assert facts.intent == "penalty_prediction"
    assert facts.domain == "drug_crime"
    assert facts.act == "tàng trữ"
    assert facts.substance == "methamphetamine"
    assert facts.normalized_quantity_g == 2.0

    _, facts = extract_legal_facts("Vận chuyển 500mg heroin")
    assert facts.act == "vận chuyển"
    assert facts.substance == "heroin"
    assert facts.normalized_quantity_g == 0.5

    _, facts = extract_legal_facts("Mua bán 1kg cần sa")
    assert facts.act == "mua bán"
    assert facts.substance == "cannabis"
    assert facts.normalized_quantity_g == 1000.0

    _, facts = extract_legal_facts("Tôi bị bắt vì ma túy")
    assert facts.domain == "drug_crime"
    assert facts.substance == "unknown_drug"
    assert facts.normalized_quantity_g is None


def test_agentic_missing_info_asks_follow_up():
    response = run_agentic_rag(AgenticChatRequest(
        message="Tôi bị bắt vì ma túy thì bị phạt bao nhiêu?",
        conversation_id="agentic-missing",
        mode="agentic",
        include_debug=True,
    ))

    assert response.status == "need_more_info"
    assert set(response.missing_fields) == {"act", "substance", "quantity"}
    assert response.agent_trace
    assert any(step.action == "ASK_FOLLOW_UP" for step in response.agent_trace)


def test_agentic_conversation_state_merges_follow_up(monkeypatch):
    conversation_state_store.clear_state("agentic-merge")
    first = run_agentic_rag(AgenticChatRequest(
        message="Tôi bị bắt vì ma túy thì bị phạt bao nhiêu?",
        conversation_id="agentic-merge",
        mode="agentic",
        include_debug=True,
    ))
    assert first.status == "need_more_info"

    monkeypatch.setattr("app.services.agentic_rag_service.normalize_text_with_graph", lambda _: [])
    monkeypatch.setattr("app.services.agentic_rag_service.retrieve_candidates", lambda *args, **kwargs: ([{"article_code": "249", "title": "Điều 249", "score": 1.0}], {}))
    monkeypatch.setattr("app.services.agentic_rag_service.rerank", lambda _q, candidates, _top_k: candidates)
    monkeypatch.setattr("app.services.agentic_rag_service.graph_retriever.fetch_contexts", lambda _codes: [_drug_context()])

    second = run_agentic_rag(AgenticChatRequest(
        message="Tàng trữ 2g ma túy đá",
        conversation_id="agentic-merge",
        mode="agentic",
        include_debug=True,
    ))

    assert second.status in {"answered", "candidate"}
    assert second.facts["act"] == "tàng trữ"
    assert second.facts["substance"] == "methamphetamine"
    assert second.facts["normalized_quantity_g"] == 2.0
    assert any(step.action == "RETRIEVE_GRAPH" for step in second.agent_trace or [])


def test_agentic_complete_drug_question_retrieves_graph(monkeypatch):
    monkeypatch.setattr("app.services.agentic_rag_service.normalize_text_with_graph", lambda _: [])
    monkeypatch.setattr("app.services.agentic_rag_service.retrieve_candidates", lambda *args, **kwargs: ([{"article_code": "249", "title": "Điều 249", "score": 1.0}], {}))
    monkeypatch.setattr("app.services.agentic_rag_service.rerank", lambda _q, candidates, _top_k: candidates)
    monkeypatch.setattr("app.services.agentic_rag_service.graph_retriever.fetch_contexts", lambda _codes: [_drug_context()])

    response = run_agentic_rag(AgenticChatRequest(
        message="Tàng trữ 2g ma túy đá thì bị phạt bao nhiêu?",
        conversation_id="agentic-complete",
        mode="agentic",
        include_debug=True,
    ))

    assert response.status in {"answered", "candidate"}
    assert response.reasoning
    assert response.citations
    assert any(step.action == "RETRIEVE_GRAPH" for step in response.agent_trace or [])


def test_agentic_lookup_chooses_fast_path(monkeypatch):
    monkeypatch.setattr("app.services.agentic_rag_service.graph_retriever.fetch_contexts", lambda _codes: [_drug_context()])

    response = run_agentic_rag(AgenticChatRequest(
        message="Điều 249 quy định gì?",
        mode="auto",
        include_debug=True,
    ))

    assert response.status == "answered"
    assert any(step.action == "RETRIEVE_FAST" for step in response.agent_trace or [])


def test_agentic_api_need_more_info():
    client = TestClient(app)
    response = client.post("/api/agentic-rag/query", json={
        "message": "Tôi bị bắt vì ma túy thì bị phạt bao nhiêu?",
        "conversation_id": "agentic-api",
        "mode": "agentic",
        "include_debug": True,
    })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "need_more_info"
    assert "agent_trace" in data


def _drug_context() -> dict:
    return {
        "article": {"article_code": "249", "title": "Tội tàng trữ trái phép chất ma túy"},
        "crime": {"name": "Tội tàng trữ trái phép chất ma túy"},
        "clauses": [{"clause_no": "1", "text": "Người nào tàng trữ trái phép chất ma túy..."}],
        "points": [],
        "conditions": [{"id": "cond-249-meth", "text": "Methamphetamine từ 0,1g đến dưới 5g"}],
        "penalty_frames": [{"id": "pf-249-1", "text": "Phạt tù từ 01 năm đến 05 năm"}],
        "penalties": [],
        "act_requirements": [{"text": "tàng trữ"}],
        "subject_requirements": [],
        "object_requirements": [],
        "consequence_requirements": [],
        "quantity_thresholds": [{"text": "Methamphetamine từ 0,1g đến dưới 5g"}],
        "exceptions": [],
        "mitigating_factors": [],
        "aggravating_factors": [],
        "references": [],
    }
