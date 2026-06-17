from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.fact_extractor import extract_facts
from app.services.session_store import session_store


SCENARIO = (
    "Tân và Thuận là bạn thân. Long nhờ Tân đặt phòng karaoke qua Thuận để Long sử dụng ma túy. "
    "Công an thu giữ một gói nghi Ketamine và hai viên ma túy tổng hợp. Các đối tượng dương tính."
)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch):
    session_store.clear()
    extract_facts.cache_clear()
    monkeypatch.setattr(settings, "use_llm_fact_extractor", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    yield
    session_store.clear()
    extract_facts.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _first(client: TestClient) -> dict:
    response = client.post("/chat/legal", json={"message": SCENARIO})
    assert response.status_code == 200
    return response.json()


def test_request_message_only_answers_only_and_both(client: TestClient):
    first = _first(client)
    assert first["clarification"]["questions"]

    answer_only = client.post("/chat/legal", json={
        "case_id": first["case_id"],
        "case_version": first["case_version"],
        "message": "",
        "answers": [{"question_id": "q_tablets_forensic_substance", "selected_option_ids": ["unknown"]}],
    })
    assert answer_only.status_code == 200
    second = answer_only.json()
    assert second["case_version"] == first["case_version"] + 1

    both = client.post("/chat/legal", json={
        "case_id": second["case_id"],
        "case_version": second["case_version"],
        "message": "Bổ sung: có camera ở hành lang.",
        "answers": [{"question_id": "q_money_source", "selected_option_ids": ["long"]}],
    })
    assert both.status_code == 200


def test_request_without_message_and_answers_is_rejected(client: TestClient):
    response = client.post("/chat/legal", json={"message": "", "answers": []})

    assert response.status_code == 422


def test_invalid_question_id_and_option_id_are_rejected(client: TestClient):
    first = _first(client)

    bad_question = client.post("/chat/legal", json={
        "case_id": first["case_id"],
        "case_version": first["case_version"],
        "answers": [{"question_id": "q_not_issued", "selected_option_ids": ["unknown"]}],
    })
    assert bad_question.status_code == 422

    bad_option = client.post("/chat/legal", json={
        "case_id": first["case_id"],
        "case_version": first["case_version"],
        "answers": [{"question_id": "q_tablets_forensic_substance", "selected_option_ids": ["bad_option"]}],
    })
    assert bad_option.status_code == 422


def test_answer_belonging_to_another_case_is_rejected(client: TestClient):
    first = _first(client)
    second = client.post("/chat/legal", json={"message": "A có một gói nghi ma túy."}).json()

    response = client.post("/chat/legal", json={
        "case_id": second["case_id"],
        "case_version": second["case_version"],
        "answers": [{"question_id": "q_tablets_forensic_substance", "selected_option_ids": ["unknown"]}],
    })

    assert response.status_code == 400
    assert first["case_id"] != second["case_id"]


def test_stale_case_version_returns_conflict(client: TestClient):
    first = _first(client)

    response = client.post("/chat/legal", json={
        "case_id": first["case_id"],
        "case_version": 0,
        "answers": [{"question_id": "q_tablets_forensic_substance", "selected_option_ids": ["unknown"]}],
    })

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "case_version_conflict"


def test_other_requires_free_text(client: TestClient):
    first = _first(client)

    response = client.post("/chat/legal", json={
        "case_id": first["case_id"],
        "case_version": first["case_version"],
        "answers": [{"question_id": "q_tablets_forensic_substance", "selected_option_ids": ["other"]}],
    })

    assert response.status_code == 422


def test_number_min_value_is_validated(client: TestClient):
    first = _first(client)
    second = client.post("/chat/legal", json={
        "case_id": first["case_id"],
        "case_version": first["case_version"],
        "answers": [{"question_id": "q_powder_forensic_substance", "selected_option_ids": ["ketamine"]}],
    }).json()
    assert any(question["id"] == "q_powder_net_mass" for question in second["clarification"]["questions"])

    response = client.post("/chat/legal", json={
        "case_id": first["case_id"],
        "case_version": second["case_version"],
        "answers": [{"question_id": "q_powder_net_mass", "value": -0.1}],
    })

    assert response.status_code == 422


def test_unissued_dependency_question_is_rejected(client: TestClient):
    first = _first(client)

    response = client.post("/chat/legal", json={
        "case_id": first["case_id"],
        "case_version": first["case_version"],
        "answers": [{"question_id": "q_powder_net_mass", "value": 1.2}],
    })

    assert response.status_code == 422


def test_client_cannot_send_fact_path_in_answer(client: TestClient):
    first = _first(client)

    response = client.post("/chat/legal", json={
        "case_id": first["case_id"],
        "case_version": first["case_version"],
        "answers": [{
            "question_id": "q_tablets_forensic_substance",
            "selected_option_ids": ["mdma"],
            "fact_path": "exhibits.tablets.confirmed_substance",
        }],
    })

    assert response.status_code == 422
