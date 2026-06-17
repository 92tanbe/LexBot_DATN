from app.models.conversation import CaseStatus
from app.models.legal_output import CandidateArticle, LegalReasoningItem, ScenarioAnalysisResponse
from app.core.config import settings
from app.services.fact_extractor import extract_facts
from app.services.legal_pipeline import _required_event_codes_from_scenario
from app.services.answer_generator import generate_answer
from app.services.dialogue_manager import handle_legal_chat
from app.services.session_store import session_store


KHANH_SCENARIO = """
Bùi Đình Khánh cùng các đồng phạm hình thành một đường dây mua bán, vận chuyển ma túy liên tỉnh với số lượng lớn
để đưa sang Trung Quốc tiêu thụ. Nhóm thuê căn hộ tại chung cư GreenBay Garden, Quảng Ninh để cất giấu 40 bánh heroin.
Khánh chuẩn bị súng AK, hộp tiếp đạn và lựu đạn. Khi công an vây bắt, Khánh dùng súng AK bắn thẳng về phía lực lượng
chức năng làm Thiếu tá Nguyễn Đăng Khải hy sinh. Khánh tiếp tục truy đuổi xe công an và nổ súng làm hư hỏng xe.
"""


def test_multi_event_scenario_forces_core_crime_articles():
    facts = extract_facts(KHANH_SCENARIO)
    codes = [item["article_code"] for item in _required_event_codes_from_scenario(KHANH_SCENARIO, facts)]

    assert {"123", "178", "251", "304"}.issubset(set(codes))
    assert "250" not in codes
    assert "sử dụng" not in facts.actions
    actor_names = {actor.name for actor in facts.actors}
    assert "Trung Quốc" not in actor_names
    assert "GreenBay Garden" not in actor_names
    assert "Quảng Ninh" not in actor_names


def test_actor_breakdown_answer_groups_by_person(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    facts = extract_facts(KHANH_SCENARIO)
    reasoning = [
        LegalReasoningItem(
            article_code="123",
            title="Tội giết người",
            crime_name="Tội giết người",
            classification="crime_candidate",
            why_relevant="Hành vi bắn thẳng làm cán bộ công an hy sinh.",
            possible_penalty_frames=[{"text": "phạt tù từ 12 năm đến 20 năm, tù chung thân hoặc tử hình"}],
            confidence=0.95,
        ),
        LegalReasoningItem(
            article_code="251",
            title="Tội mua bán trái phép chất ma túy",
            crime_name="Tội mua bán trái phép chất ma túy",
            classification="crime_candidate",
            why_relevant="Hành vi tham gia đường dây mua bán heroin.",
            possible_penalty_frames=[{"text": "tù chung thân hoặc tử hình"}],
            confidence=0.95,
        ),
    ]

    answer = generate_answer(
        KHANH_SCENARIO,
        facts,
        [],
        reasoning,
        [],
        force_actor_breakdown=True,
    )

    assert "Bùi Đình Khánh:" in answer
    assert "Điều 123" in answer
    assert "Điều 251" in answer
    assert "Nguyễn Đăng Khải:" in answer
    assert "không phải đối tượng phạm tội" in answer


def test_actor_breakdown_treats_police_officer_in_parentheses_as_victim(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    scenario = (
        "Bùi Đình Khánh sử dụng súng AK bắn thẳng về phía lực lượng chức năng. "
        "Hành vi này khiến Thiếu tá Nguyễn Đăng Khải (cán bộ Phòng Cảnh sát điều tra tội phạm về ma túy) "
        "trúng đạn và hy sinh. Khánh tiếp tục nổ súng làm hư hỏng xe."
    )
    facts = extract_facts(scenario)
    reasoning = [
        LegalReasoningItem(
            article_code="123",
            title="Tội giết người",
            crime_name="Tội giết người",
            classification="crime_candidate",
            why_relevant="Hành vi bắn thẳng làm cán bộ công an hy sinh.",
            confidence=0.95,
        )
    ]

    answer = generate_answer(scenario, facts, [], reasoning, [], force_actor_breakdown=True)

    assert "Nguyễn Đăng Khải:" in answer
    victim_section = answer.split("Nguyễn Đăng Khải:", 1)[1]
    assert "không phải đối tượng phạm tội" in victim_section
    assert "Điều 251" not in victim_section


def test_legal_chat_drug_missing_quantity_collects_facts():
    response = handle_legal_chat("A rủ B đi bay phòng, có ketamin và thuốc lắc.")

    assert response.status == CaseStatus.collecting_facts
    assert any("giám định" in item.description for item in response.missing_facts)
    assert any("khối lượng" in item.description or "hàm lượng" in item.description for item in response.missing_facts)
    assert response.clarifying_questions
    assert "Chưa đủ dữ kiện" in response.final_answer
    assert "khung hình phạt" not in response.final_answer.lower() or "chưa chốt" in response.final_answer.lower()


def test_legal_chat_merges_added_drug_quantities(monkeypatch):
    captured = {}

    def fake_run_legal_analysis(scenario, facts=None, top_k=8, include_debug=False, answer_style="auto"):
        captured["scenario"] = scenario
        captured["facts"] = facts
        from app.models.legal_output import ScenarioAnalysisResponse

        return ScenarioAnalysisResponse(
            facts=facts,
            final_answer="Tóm tắt dữ kiện đã xác định và phân tích điều luật ở mức tham khảo.",
            confidence=0.7,
            warnings=[],
        )

    monkeypatch.setattr("app.services.dialogue_manager.run_legal_analysis", fake_run_legal_analysis)

    first = handle_legal_chat("A rủ B đi bay phòng, có ketamin và thuốc lắc.")
    second = handle_legal_chat(
        "Có kết luận giám định, ketamine 1g, MDMA 0.5g, A đặt phòng và nhờ người mua, B cùng sử dụng.",
        case_id=first.case_id,
    )

    assert second.status in {CaseStatus.ready_to_answer, CaseStatus.answered}
    assert captured["facts"].quantities
    assert len(captured["facts"].substances) >= 2
    assert "A rủ B" in captured["scenario"]
    assert "ketamine 1g" in captured["scenario"]
    assert "phân tích điều luật" in second.final_answer


def test_legal_chat_accomplice_missing_roles():
    response = handle_legal_chat("A và B cùng tham gia vụ trộm nhưng chưa rõ ai làm gì.")

    assert response.status == CaseStatus.collecting_facts
    assert any("vai trò" in item.description.lower() for item in response.missing_facts)
    assert any("Vai trò" in question or "vai trò" in question for question in response.clarifying_questions)
    assert "Chưa đủ dữ kiện" in response.final_answer


def test_legal_chat_user_does_not_know_more_stops_reasking():
    response = handle_legal_chat("Tôi không biết thêm thông tin.")

    assert response.status == CaseStatus.insufficient_information
    assert response.clarifying_questions == []
    assert "dừng hỏi lặp" in response.final_answer
    assert "sơ bộ" in response.final_answer


def test_collecting_response_can_include_neo4j_provisional_analysis(monkeypatch):
    session_store.clear()
    monkeypatch.setattr(settings, "use_provisional_neo4j_analysis", True)

    def fake_run_legal_analysis(
        scenario,
        facts=None,
        top_k=8,
        include_debug=False,
        answer_style="auto",
        generate_final_answer=True,
    ):
        return ScenarioAnalysisResponse(
            facts=facts,
            candidate_articles=[
                CandidateArticle(
                    article_code="255",
                    title="Tội tổ chức sử dụng trái phép chất ma túy",
                    crime_name="Tội tổ chức sử dụng trái phép chất ma túy",
                    score=0.78,
                    source="test",
                ),
                CandidateArticle(
                    article_code="250",
                    title="Tội vận chuyển trái phép chất ma túy",
                    crime_name="Tội vận chuyển trái phép chất ma túy",
                    score=0.8,
                    source="test",
                )
            ],
            legal_reasoning=[
                LegalReasoningItem(
                    article_code="255",
                    title="Tội tổ chức sử dụng trái phép chất ma túy",
                    crime_name="Tội tổ chức sử dụng trái phép chất ma túy",
                    classification="crime_candidate",
                    finding_status="insufficient_evidence",
                    why_relevant="Khớp hành vi tổ chức sử dụng ma túy.",
                    missing_elements=["Ma túy: thiếu kết luận giám định về loại chất của tang vật."],
                    confidence=0.78,
                ),
                LegalReasoningItem(
                    article_code="250",
                    title="Tội vận chuyển trái phép chất ma túy",
                    crime_name="Tội vận chuyển trái phép chất ma túy",
                    classification="crime_candidate",
                    finding_status="insufficient_evidence",
                    why_relevant="Không nên ưu tiên nếu tình huống không nêu vận chuyển.",
                    confidence=0.8,
                )
            ],
            final_answer="",
            confidence=0.78,
            warnings=["provisional_analysis_from_neo4j"],
        )

    monkeypatch.setattr("app.services.dialogue_manager.run_legal_analysis", fake_run_legal_analysis)

    response = handle_legal_chat("A tổ chức sử dụng ma túy đá nhưng chưa có kết luận giám định.")

    assert response.status == CaseStatus.collecting_facts
    assert response.candidate_articles[0].article_code == "255"
    assert all(article.article_code != "250" for article in response.candidate_articles)
    assert response.legal_reasoning[0].article_code == "255"
    assert all(item.article_code != "250" for item in response.legal_reasoning)
    assert response.provisional_findings[0].status == "possible_hypothesis"
    assert "Nhận định tạm thời từ dữ liệu Neo4j" in response.final_answer


def test_analysis_mode_answers_without_clarification_form(monkeypatch):
    session_store.clear()
    monkeypatch.setattr(settings, "use_provisional_neo4j_analysis", True)

    def fake_run_legal_analysis(
        scenario,
        facts=None,
        top_k=8,
        include_debug=False,
        answer_style="auto",
        generate_final_answer=True,
    ):
        return ScenarioAnalysisResponse(
            facts=facts,
            candidate_articles=[
                CandidateArticle(
                    article_code="251",
                    title="Tội mua bán trái phép chất ma túy",
                    crime_name="Tội mua bán trái phép chất ma túy",
                    score=0.82,
                    source="test",
                )
            ],
            legal_reasoning=[
                LegalReasoningItem(
                    article_code="251",
                    title="Tội mua bán trái phép chất ma túy",
                    crime_name="Tội mua bán trái phép chất ma túy",
                    classification="crime_candidate",
                    finding_status="insufficient_evidence",
                    why_relevant="Tình huống có dấu hiệu đường dây mua bán ma túy.",
                    missing_elements=["Ma túy: thiếu kết luận giám định về loại chất của tang vật."],
                    confidence=0.82,
                )
            ],
            final_answer="",
            confidence=0.82,
            warnings=[],
        )

    def fake_generate_answer(*args, **kwargs):
        return "Có thể xem xét Điều 251 đối với hành vi mua bán trái phép chất ma túy; các dữ kiện giám định chỉ là giới hạn khi chốt khoản."

    monkeypatch.setattr("app.services.dialogue_manager.run_legal_analysis", fake_run_legal_analysis)
    monkeypatch.setattr("app.services.dialogue_manager.generate_answer", fake_generate_answer)

    response = handle_legal_chat(
        "A hình thành đường dây mua bán ma túy nhưng chưa nêu kết luận giám định.",
        mode="agentic",
    )

    assert response.status == CaseStatus.answered
    assert response.clarification is None
    assert response.missing_facts == []
    assert response.clarifying_questions == []
    assert "Điều 251" in response.final_answer
