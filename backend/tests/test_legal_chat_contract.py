import pytest
from pydantic import ValidationError

from app.models.chat import LegalChatRequest


def test_legal_chat_accepts_empty_message_with_answers():
    req = LegalChatRequest(
        message="",
        case_id="case-1",
        case_version=1,
        answers=[
            {
                "question_id": "q_tablets_forensic_substance",
                "selected_option_ids": ["mdma"],
                "value": None,
                "free_text": None,
            }
        ],
    )

    assert req.message == ""
    assert req.case_id == "case-1"
    assert req.case_version == 1
    assert req.answers[0].question_id == "q_tablets_forensic_substance"


def test_legal_chat_rejects_empty_message_without_answers():
    with pytest.raises(ValidationError):
        LegalChatRequest(message="", answers=[])


def test_legal_chat_answer_forbids_fact_path():
    with pytest.raises(ValidationError):
        LegalChatRequest(
            message="",
            case_id="case-1",
            case_version=1,
            answers=[
                {
                    "question_id": "q1",
                    "selected_option_ids": ["yes"],
                    "value": None,
                    "free_text": None,
                    "fact_path": "exhibits.tablets.forensic_substance",
                }
            ],
        )


def test_legal_chat_request_forbids_fact_patch_fields():
    with pytest.raises(ValidationError):
        LegalChatRequest(
            message="A rủ B đi bay phòng.",
            fact_path="exhibits.tablets.forensic_substance",
        )
