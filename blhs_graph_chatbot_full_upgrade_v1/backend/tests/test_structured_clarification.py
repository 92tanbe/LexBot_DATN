from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.conversation import CaseStatus, ClarificationAnswer
from app.services.dialogue_manager import handle_legal_chat
from app.services.fact_extractor import extract_facts
from app.services.input_understanding import InputUnderstanding
from app.services.session_store import session_store


DRUG_SCENARIO = (
    "Tân và Thuận là bạn thân. Long nhờ Tân đặt phòng karaoke qua Thuận để Long sử dụng ma túy "
    "ở phòng với nhiều người khác. Long đồng thời nhờ Tân mua qua Thuận để Thuận mua ma túy từ "
    "một người tên Bí và đem đến cho Long. Khi Long cùng Văn, Tiến, Sang và bốn nhân viên bị công "
    "an bắt, thu giữ một gói nghi Ketamine và hai viên ma túy tổng hợp. Các đối tượng đều dương tính "
    "với ma túy."
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


def test_first_turn_returns_structured_questions_and_legacy_texts():
    response = handle_legal_chat(DRUG_SCENARIO)

    assert response.status == CaseStatus.collecting_facts
    assert response.case_version == 1
    assert response.clarification is not None
    assert len(response.clarification.questions) <= 5
    ids = {question.id for question in response.clarification.questions}
    assert {"q_powder_forensic_substance", "q_tablets_forensic_substance", "q_tan_knowledge"} <= ids
    tablets = next(question for question in response.clarification.questions if question.id == "q_tablets_forensic_substance")
    assert tablets.input_type == "single_choice"
    assert tablets.fact_path == "exhibits.tablets.forensic_substance"
    assert [option.id for option in tablets.options] == [
        "mdma",
        "methamphetamine",
        "ketamine",
        "other",
        "not_narcotic",
        "no_forensic_report",
        "unknown",
    ]
    assert response.clarifying_questions == [question.text for question in response.clarification.questions]


def test_drug_facts_do_not_infer_mdma_or_forensic_from_toxicology():
    response = handle_legal_chat(DRUG_SCENARIO)

    tablets = next(exhibit for exhibit in response.facts.exhibits if exhibit.id == "tablets")
    assert tablets.suspected_substance == "ma túy tổng hợp"
    assert tablets.confirmed_substance is None
    assert tablets.forensic_status != "forensic_confirmed"
    assert any("dương tính" in item.description for item in response.missing_facts)
    assert "tổ chức sử dụng" not in response.facts.actions
    assert response.status == CaseStatus.collecting_facts


def test_second_turn_answers_merge_and_activate_dependent_mass_questions():
    first = handle_legal_chat(DRUG_SCENARIO)
    second = handle_legal_chat(
        "",
        case_id=first.case_id,
        case_version=first.case_version,
        answers=[
            ClarificationAnswer(question_id="q_powder_forensic_substance", selected_option_ids=["ketamine"]),
            ClarificationAnswer(question_id="q_tablets_forensic_substance", selected_option_ids=["mdma"]),
            ClarificationAnswer(question_id="q_tan_knowledge", selected_option_ids=["knew_group_use"]),
            ClarificationAnswer(question_id="q_money_source", selected_option_ids=["long"]),
        ],
    )

    assert second.case_version == 2
    assert second.facts.structured_facts["exhibits.powder.confirmed_substance"] == "Ketamine"
    assert second.facts.structured_facts["exhibits.tablets.confirmed_substance"] == "MDMA"
    assert second.facts.structured_facts["transactions.drug_purchase.money_source"] == "Long"
    ids = [question.id for question in second.clarification.questions]
    assert "q_tablets_forensic_substance" not in ids
    assert "q_tan_knowledge" not in ids
    assert "q_powder_net_mass" in ids
    mass_question = next(question for question in second.clarification.questions if question.id == "q_powder_net_mass")
    assert mass_question.depends_on_question_id == "q_powder_forensic_substance"
    assert mass_question.input_type == "number"


def test_unknown_answer_is_stored_and_not_reasked_immediately():
    first = handle_legal_chat(DRUG_SCENARIO)
    second = handle_legal_chat(
        "",
        case_id=first.case_id,
        case_version=first.case_version,
        answers=[ClarificationAnswer(question_id="q_tablets_forensic_substance", selected_option_ids=["unknown"])],
    )

    session = session_store.get(first.case_id)
    assert session is not None
    assert "q_tablets_forensic_substance" in session.answered_unknown_question_ids
    assert all(question.id != "q_tablets_forensic_substance" for question in second.clarification.questions)


def test_backend_runs_without_openai_key():
    settings.openai_api_key = ""
    settings.use_llm_fact_extractor = False

    response = handle_legal_chat("A rủ B đi bay phòng, có hai viên ma túy tổng hợp.")

    assert response.status == CaseStatus.collecting_facts
    assert response.clarification is not None
    assert response.clarifying_questions


def test_unspecified_powder_question_is_neutral_and_missing_questions_do_not_misalign():
    response = handle_legal_chat(
        "Long và Mẫn bị bắt ở phòng karaoke, 2 người đã dương tính và còn dư 2 gam bột ở trong phòng."
    )

    powder = next(exhibit for exhibit in response.facts.exhibits if exhibit.id == "powder")
    assert powder.quantity is not None
    assert powder.quantity.value == 2

    powder_question = next(
        question
        for question in response.clarification.questions
        if question.id == "q_powder_forensic_substance"
    )
    assert "Ketamine" not in powder_question.text
    assert "chất bột" in powder_question.text

    role_missing_items = [item for item in response.missing_facts if item.key == "actors.roles"]
    assert all(not item.question or "giám định" not in item.question for item in role_missing_items)


def test_natural_language_answer_to_issued_forensic_question_is_merged():
    first = handle_legal_chat(
        "Long và Mẫn bị bắt ở phòng karaoke, 2 người đã dương tính và còn dư 2 gam bột ở trong phòng."
    )
    assert any(question.id == "q_powder_forensic_substance" for question in first.clarification.questions)

    second = handle_legal_chat(
        "Đó là chất ma túy đá.",
        case_id=first.case_id,
        case_version=first.case_version,
        include_debug=True,
    )

    assert second.facts.structured_facts["exhibits.powder.confirmed_substance"] == "Methamphetamine"
    powder = next(exhibit for exhibit in second.facts.exhibits if exhibit.id == "powder")
    assert powder.confirmed_substance == "Methamphetamine"
    assert powder.forensic_status == "forensic_confirmed"
    assert all(question.id != "q_powder_forensic_substance" for question in second.clarification.questions)
    assert "q_powder_forensic_substance" in second.debug["answered_question_ids"]


def test_named_drug_case_filters_org_fragments_and_detects_payment_evidence():
    scenario = (
        "Ca sĩ Long Nhật (tên thật: Đinh Long Nhật) bị Cơ quan Cảnh sát điều tra Công an TP.HCM "
        "khởi tố cùng với ca sĩ Sơn Ngọc Minh trong chuyên án ma túy. Hành vi vi phạm: Long Nhật "
        "bị điều tra về hành vi tổ chức sử dụng trái phép chất ma túy. Lời khai tại cơ quan điều tra: "
        "Nam ca sĩ thừa nhận có sử dụng ma túy đá. Anh khai nhận đã mua ma túy với giá 500.000 đồng "
        "để sử dụng cùng người giúp việc kiêm quản lý tại nhà riêng. Hình thức giao dịch: chuyển khoản, "
        "bao gồm 500.000 đồng tiền mua ma túy và 500.000 đồng phí giao hàng."
    )

    response = handle_legal_chat(scenario)

    names = {actor.name for actor in response.facts.actors}
    assert {"Đinh Long Nhật", "Sơn Ngọc Minh", "Người giúp việc quản lý"} <= names
    assert names.isdisjoint({"TP", "HCM", "Long", "Đinh", "Cảnh", "Công", "Hành", "Lời", "Anh", "Hình", "Giao", "Ca"})
    assert response.facts.structured_facts["transactions.drug_purchase.money_source"] == "Đinh Long Nhật"
    assert response.facts.structured_facts["transactions.drug_purchase.price"] == 500000
    assert response.facts.structured_facts["transactions.drug_purchase.delivery_fee"] == 500000
    assert response.facts.structured_facts["evidence.electronic"] == ["bank_transfer"]

    question_ids = {question.id for question in response.clarification.questions}
    assert "q_money_source" not in question_ids
    assert "q_electronic_evidence" not in question_ids
    missing_text = " ".join(item.description for item in response.missing_facts)
    assert "hưởng lợi" not in missing_text
    assert "ai mua" not in missing_text

    second = handle_legal_chat(
        "",
        case_id=response.case_id,
        case_version=response.case_version,
        answers=[ClarificationAnswer(question_id="q_incident_time", value="2024-01-01")],
    )
    follow_up_text = " ".join(second.clarifying_questions)
    assert "Ai là người mua hoặc đặt mua" not in follow_up_text
    assert "Có ai hưởng lợi" not in follow_up_text


def test_criminal_law_extraction_keeps_original_message_when_llm_normalizes(monkeypatch: pytest.MonkeyPatch):
    scenario = (
        "Ca sĩ Long Nhật (tên thật: Đinh Long Nhật) khai đã mua ma túy với giá 500.000 đồng "
        "để sử dụng cùng người giúp việc kiêm quản lý. Giao dịch chuyển khoản gồm "
        "500.000 đồng tiền mua ma túy và 500.000 đồng phí giao hàng."
    )
    normalized_without_key_details = (
        "Long Nhật khai mua ma túy với giá 500.000 đồng để sử dụng cùng người giúp việc. "
        "Giao dịch chuyển khoản gồm tiền mua ma túy và phí giao hàng."
    )

    def fake_understand_input(_message: str) -> InputUnderstanding:
        return InputUnderstanding(
            scope="criminal_law",
            should_run_pipeline=True,
            normalized_message=normalized_without_key_details,
            source="llm",
        )

    monkeypatch.setattr("app.services.dialogue_manager.understand_input", fake_understand_input)

    response = handle_legal_chat(scenario)

    assert {actor.name for actor in response.facts.actors} >= {"Đinh Long Nhật", "Người giúp việc quản lý"}
    assert response.facts.structured_facts["transactions.drug_purchase.money_source"] == "Đinh Long Nhật"
    assert response.facts.structured_facts["transactions.drug_purchase.delivery_fee"] == 500000
