from app.services.fact_extractor import extract_facts
from app.services.answer_generator import generate_answer
from app.services.clarifying_questions import build_clarifying_questions
from app.services.legal_matcher import detect_missing_facts


def test_fact_extractor_drug_age_quantity():
    facts = extract_facts("A 17 tuổi mua 2 viên thuốc lắc cho bạn dùng trong karaoke")
    assert facts.actors[0].age == 17
    assert facts.quantities[0].raw_text == "2 viên"
    assert facts.substances


def test_missing_drug_forensics():
    facts = extract_facts("A rủ B đi bay phòng, có ketamin trong phòng karaoke")
    missing = detect_missing_facts(facts, "")
    assert any("giám định" in m for m in missing)


def test_drug_clarifying_questions_cover_core_gaps():
    scenario = "A rủ B đi bay phòng, có ketamin trong phòng karaoke"
    facts = extract_facts(scenario)
    missing = detect_missing_facts(facts, scenario)
    questions = build_clarifying_questions(facts, scenario, missing)

    assert any("khối lượng" in question or "số lượng" in question for question in questions)
    assert any("tang vật" in question and "tiêu thụ" in question for question in questions)
    assert any("người bán" in question or "cung cấp" in question for question in questions)
    assert any("rủ rê" in question or "địa điểm" in question for question in questions)


def test_drug_clarifying_questions_for_consumed_exhibit():
    scenario = "A rủ B sử dụng ketamin, tang vật đã tiêu thụ hết nên không còn tang vật khi bị bắt"
    facts = extract_facts(scenario)
    missing = detect_missing_facts(facts, scenario)
    questions = build_clarifying_questions(facts, scenario, missing)

    assert any("xét nghiệm dương tính" in question for question in questions)
    assert not any("trường hợp nào" in question for question in questions)


def test_fact_extractor_detects_seized_exhibit():
    facts = extract_facts("Công an phát hiện tang vật 3 gói ketamin trong phòng karaoke")

    assert facts.exhibits
    assert facts.exhibits[0].status == "seized"
    assert facts.exhibits[0].quantity is not None


def test_unknown_extra_data_stops_reasking_and_gives_limited_conclusion():
    scenario = "A sử dụng ma túy trong phòng karaoke. Tôi không biết tang vật và không biết định lượng."
    facts = extract_facts(scenario)
    missing = detect_missing_facts(facts, scenario)
    questions = build_clarifying_questions(facts, scenario, missing)
    answer = generate_answer(scenario, facts, [], [], missing, clarifying_questions=questions)
    lowered_answer = answer.lower()

    assert questions == []
    assert "chưa có thêm dữ liệu" in answer or "chưa có thêm thông tin" in answer
    assert "có dấu hiệu" in lowered_answer or "có thể xem xét" in lowered_answer
