from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.conversation import CaseStatus, ClarificationAnswer
from app.services.dialogue_manager import handle_legal_chat
from app.services.fact_extractor import extract_facts
from app.services.session_store import session_store


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch):
    session_store.clear()
    extract_facts.cache_clear()
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "use_llm_input_understanding", False)
    yield
    session_store.clear()
    extract_facts.cache_clear()


def _article_123_context() -> dict:
    return {
        "article": {
            "article_code": "123",
            "title": "Tội giết người",
            "full_text": "Điều 123. Tội giết người",
        },
        "crime": {"name": "Tội giết người"},
        "clauses": [
            {
                "id": "article_123_clause_1",
                "article_code": "123",
                "clause_no": 1,
                "role": "penalty_frame",
                "text": (
                    "Người nào giết người thuộc một trong các trường hợp sau đây: "
                    "a) Giết 02 người trở lên; "
                    "b) Giết người dưới 16 tuổi; "
                    "c) Giết phụ nữ mà biết là có thai; "
                    "d) Giết người đang thi hành công vụ hoặc vì lý do công vụ của nạn nhân; "
                    "đ) Giết ông, bà, cha, mẹ, người nuôi dưỡng, thầy giáo, cô giáo của mình."
                ),
            },
            {
                "id": "article_123_clause_2",
                "article_code": "123",
                "clause_no": 2,
                "role": "penalty_frame",
                "text": "Phạm tội không thuộc các trường hợp quy định tại khoản 1 Điều này.",
            },
            {
                "id": "article_123_clause_3",
                "article_code": "123",
                "clause_no": 3,
                "role": "penalty_frame",
                "text": "Người chuẩn bị phạm tội này.",
            },
            {
                "id": "article_123_clause_4",
                "article_code": "123",
                "clause_no": 4,
                "role": "additional_penalty",
                "text": "Người phạm tội còn có thể bị cấm hành nghề.",
            },
        ],
        "points": [
            {
                "id": "article_123_clause_1_point_a",
                "article_code": "123",
                "clause_id": "article_123_clause_1",
                "clause_no": 1,
                "point": "a",
                "text": "Giết 02 người trở lên;",
            },
            {
                "id": "article_123_clause_1_point_b",
                "article_code": "123",
                "clause_id": "article_123_clause_1",
                "clause_no": 1,
                "point": "b",
                "text": "Giết người dưới 16 tuổi;",
            },
        ],
        "penalty_frames": [
            {
                "owner_id": "article_123_clause_1",
                "article_code": "123",
                "penalty_type": "imprisonment",
                "text": "phạt tù từ 12 năm đến 20 năm",
                "has_life_imprisonment": True,
                "has_death_penalty": True,
            },
            {
                "owner_id": "article_123_clause_2",
                "article_code": "123",
                "penalty_type": "imprisonment",
                "text": "phạt tù từ 07 năm đến 15 năm",
            },
            {
                "owner_id": "article_123_clause_3",
                "article_code": "123",
                "penalty_type": "imprisonment",
                "text": "phạt tù từ 01 năm đến 05 năm",
            },
        ],
    }


def _simple_article_context(code: str, title: str, penalty: str = "phạt tù từ 01 năm đến 05 năm") -> dict:
    return {
        "article": {
            "article_code": code,
            "title": title,
            "full_text": f"Điều {code}. {title}",
        },
        "crime": {"name": title},
        "clauses": [
            {
                "id": f"article_{code}_clause_1",
                "article_code": code,
                "clause_no": 1,
                "role": "penalty_frame",
                "text": f"Người nào phạm {title.lower()}.",
            },
            {
                "id": f"article_{code}_clause_2",
                "article_code": code,
                "clause_no": 2,
                "role": "penalty_frame",
                "text": "Phạm tội thuộc trường hợp tăng nặng.",
            },
        ],
        "points": [],
        "penalty_frames": [
            {
                "owner_id": f"article_{code}_clause_1",
                "article_code": code,
                "penalty_type": "imprisonment",
                "text": penalty,
            },
            {
                "owner_id": f"article_{code}_clause_2",
                "article_code": code,
                "penalty_type": "imprisonment",
                "text": "phạt tù từ 03 năm đến 10 năm",
            },
        ],
    }


def _article_251_context() -> dict:
    ctx = _simple_article_context("251", "Tội mua bán trái phép chất ma túy", "phạt tù từ 03 năm đến 07 năm")
    ctx["clauses"][1]["text"] = "Phạm tội thuộc trường hợp có tổ chức."
    ctx["points"] = [
        {
            "id": "article_251_clause_2_point_a",
            "article_code": "251",
            "clause_id": "article_251_clause_2",
            "clause_no": 2,
            "point": "a",
            "text": "Có tổ chức;",
        },
    ]
    return ctx


def test_general_penalty_question_returns_article_options_from_neo4j(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.article_lookup.search_fulltext",
        lambda _message, _limit: [
            {
                "article_code": "123",
                "title": "Tội giết người",
                "score": 8.0,
                "source": "article_fulltext",
                "matched_terms": ["Tội giết người"],
            }
        ],
    )
    monkeypatch.setattr("app.services.article_lookup.fetch_contexts", lambda _codes: [_article_123_context()])

    first = handle_legal_chat("tội giết người đi mấy năm tù")

    assert first.status == CaseStatus.answered
    assert "Điều 123" in first.final_answer
    assert first.clarification is None
    assert "Khoản 1" in first.final_answer
    assert "Khoản 2" in first.final_answer
    assert "12 năm đến 20 năm" in first.final_answer
    assert "tù chung thân" in first.final_answer
    assert "tử hình" in first.final_answer


def test_exact_article_ref_wins_over_noisy_fulltext(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.article_lookup.search_exact_articles",
        lambda refs, _limit: [
            {
                "article_code": "134",
                "title": "Tội cố ý gây thương tích hoặc gây tổn hại cho sức khỏe của người khác",
                "score": 2.0,
                "source": "exact_article",
                "matched_terms": ["Điều 134"],
            }
        ] if refs == ["134"] else [],
    )
    monkeypatch.setattr(
        "app.services.article_lookup.search_fulltext",
        lambda _message, _limit: [
            {
                "article_code": "91",
                "title": "Nguyên tắc xử lý đối với người dưới 18 tuổi phạm tội",
                "score": 8.0,
                "source": "article_fulltext",
                "matched_terms": ["mức hình phạt"],
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.article_lookup.fetch_contexts",
        lambda codes: [_simple_article_context(codes[0], "Tội cố ý gây thương tích hoặc gây tổn hại cho sức khỏe của người khác")],
    )

    response = handle_legal_chat("Điều 134 mức phạt")

    assert response.status == CaseStatus.answered
    assert response.candidate_articles[0].article_code == "134"
    assert "Điều 134" in response.final_answer


def test_core_crime_title_beats_higher_but_less_exact_fulltext(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.article_lookup.search_exact_articles", lambda _refs, _limit: [])
    monkeypatch.setattr(
        "app.services.article_lookup.search_fulltext",
        lambda _message, _limit: [
            {
                "article_code": "171",
                "title": "Tội cướp giật tài sản",
                "score": 9.5,
                "source": "article_fulltext",
                "matched_terms": ["Tội cướp giật tài sản"],
            },
            {
                "article_code": "168",
                "title": "Tội cướp tài sản",
                "score": 7.9,
                "source": "article_fulltext",
                "matched_terms": ["Tội cướp tài sản"],
            },
        ],
    )
    monkeypatch.setattr(
        "app.services.article_lookup.fetch_contexts",
        lambda codes: [_simple_article_context(codes[0], "Tội cướp tài sản")],
    )

    response = handle_legal_chat("tội cướp tài sản đi mấy năm tù")

    assert response.status == CaseStatus.answered
    assert response.candidate_articles[0].article_code == "168"
    assert "Điều 168" in response.final_answer


def test_penalty_question_without_toi_keyword_can_lookup_article(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.article_lookup.search_exact_articles", lambda _refs, _limit: [])
    monkeypatch.setattr(
        "app.services.article_lookup.search_fulltext",
        lambda _message, _limit: [
            {
                "article_code": "134",
                "title": "Tội cố ý gây thương tích hoặc gây tổn hại cho sức khỏe của người khác",
                "score": 7.0,
                "source": "article_fulltext",
                "matched_terms": ["Tội cố ý gây thương tích hoặc gây tổn hại cho sức khỏe của người khác"],
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.article_lookup.fetch_contexts",
        lambda codes: [_simple_article_context(codes[0], "Tội cố ý gây thương tích hoặc gây tổn hại cho sức khỏe của người khác")],
    )

    response = handle_legal_chat("đánh người gây thương tích đi tù bao nhiêu năm")

    assert response.status == CaseStatus.answered
    assert response.candidate_articles[0].article_code == "134"
    assert response.clarification is None


def test_penalty_question_like_how_is_it_punished_uses_article_lookup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.article_lookup.search_exact_articles", lambda _refs, _limit: [])
    monkeypatch.setattr(
        "app.services.article_lookup.search_fulltext",
        lambda _message, _limit: [
            {
                "article_code": "251",
                "title": "Tội mua bán trái phép chất ma túy",
                "score": 16.0,
                "source": "article_fulltext",
                "matched_terms": ["Tội mua bán trái phép chất ma túy"],
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.article_lookup.fetch_contexts",
        lambda _codes: [_article_251_context()],
    )

    response = handle_legal_chat("buôn bán chất ma túy bị phạt như thế nào")

    assert response.status == CaseStatus.answered
    assert response.candidate_articles[0].article_code == "251"
    assert "Điều 251" in response.final_answer
    assert "phạt tù từ 03 năm đến 07 năm" in response.final_answer
    assert response.clarification is None
    assert "Khoản 1" in response.final_answer
    assert "Khoản 2" in response.final_answer


def test_multi_drug_penalty_frame_lookup_returns_all_matching_articles(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.article_lookup.search_exact_articles", lambda _refs, _limit: [])
    contexts = {
        "249": _simple_article_context("249", "Tội tàng trữ trái phép chất ma túy", "phạt tù từ 01 năm đến 05 năm"),
        "251": _article_251_context(),
    }
    monkeypatch.setattr(
        "app.services.article_lookup.fetch_contexts",
        lambda codes: [contexts[code] for code in codes if code in contexts],
    )

    response = handle_legal_chat("tội mua bán tàng trữ ma tuý bị phạt với những khung nào")

    assert response.status == CaseStatus.answered
    assert response.clarification is None
    assert response.missing_facts == []
    assert [article.article_code for article in response.candidate_articles[:2]] == ["249", "251"]
    assert "Điều 249" in response.final_answer
    assert "Điều 251" in response.final_answer
    assert "phạt tù từ 01 năm đến 05 năm" in response.final_answer
    assert "phạt tù từ 03 năm đến 07 năm" in response.final_answer


def test_forestry_penalty_frame_lookup_uses_article_232(monkeypatch: pytest.MonkeyPatch):
    contexts = {
        "232": _simple_article_context(
            "232",
            "Tội vi phạm quy định về khai thác, bảo vệ rừng và lâm sản",
            "phạt tiền từ 50.000.000 đồng đến 300.000.000 đồng hoặc phạt tù từ 06 tháng đến 03 năm",
        )
    }
    monkeypatch.setattr("app.services.article_lookup.fetch_contexts", lambda codes: [contexts[code] for code in codes if code in contexts])

    response = handle_legal_chat("tội khai thác gỗ trái phép bị phạt những khung nào")

    assert response.status == CaseStatus.answered
    assert response.clarification is None
    assert response.missing_facts == []
    assert response.candidate_articles[0].article_code == "232"
    assert "Điều 232" in response.final_answer
    assert "khai thác, bảo vệ rừng và lâm sản" in response.final_answer


def test_resource_extraction_penalty_frame_lookup_uses_article_227(monkeypatch: pytest.MonkeyPatch):
    contexts = {
        "227": _simple_article_context(
            "227",
            "Tội vi phạm quy định về nghiên cứu, thăm dò, khai thác tài nguyên",
            "phạt tiền từ 300.000.000 đồng đến 1.500.000.000 đồng hoặc phạt tù từ 06 tháng đến 03 năm",
        )
    }
    monkeypatch.setattr("app.services.article_lookup.fetch_contexts", lambda codes: [contexts[code] for code in codes if code in contexts])

    response = handle_legal_chat("tội khai thác trái phép tài nguyên bị phạt những khung nào")

    assert response.status == CaseStatus.answered
    assert response.clarification is None
    assert response.missing_facts == []
    assert response.candidate_articles[0].article_code == "227"
    assert "Điều 227" in response.final_answer
    assert "khai thác tài nguyên" in response.final_answer


def test_reactionary_colloquial_lookup_uses_national_security_articles(monkeypatch: pytest.MonkeyPatch):
    contexts = {
        "108": _simple_article_context(
            "108",
            "Tội phản bội Tổ quốc",
            "phạt tù từ 12 năm đến 20 năm",
        ),
        "109": _simple_article_context(
            "109",
            "Tội hoạt động nhằm lật đổ chính quyền nhân dân",
            "phạt tù từ 12 năm đến 20 năm hoặc tù chung thân",
        ),
    }
    monkeypatch.setattr("app.services.article_lookup.fetch_contexts", lambda codes: [contexts[code] for code in codes if code in contexts])

    response = handle_legal_chat("tội phản động tổ quốc bị phạt khung nào")

    assert response.status == CaseStatus.answered
    assert response.clarification is None
    assert [article.article_code for article in response.candidate_articles[:2]] == ["109", "108"]
    assert "Điều 109" in response.final_answer
    assert "Điều 108" in response.final_answer


def test_reactionary_short_lookup_uses_article_109(monkeypatch: pytest.MonkeyPatch):
    contexts = {
        "109": _simple_article_context(
            "109",
            "Tội hoạt động nhằm lật đổ chính quyền nhân dân",
            "phạt tù từ 12 năm đến 20 năm hoặc tù chung thân",
        ),
    }
    monkeypatch.setattr("app.services.article_lookup.fetch_contexts", lambda codes: [contexts[code] for code in codes if code in contexts])

    response = handle_legal_chat("tội phản động bị phạt khung nào")

    assert response.status == CaseStatus.answered
    assert response.candidate_articles[0].article_code == "109"
    assert "Điều 109" in response.final_answer


def test_murder_how_is_it_punished_uses_article_lookup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.article_lookup.search_exact_articles", lambda _refs, _limit: [])
    monkeypatch.setattr(
        "app.services.article_lookup.search_fulltext",
        lambda _message, _limit: [
            {
                "article_code": "123",
                "title": "Tội giết người",
                "score": 8.0,
                "source": "article_fulltext",
                "matched_terms": ["Tội giết người"],
            }
        ],
    )
    monkeypatch.setattr("app.services.article_lookup.fetch_contexts", lambda _codes: [_article_123_context()])

    response = handle_legal_chat("tội giết người bị phạt như thế nào")

    assert response.status == CaseStatus.answered
    assert response.candidate_articles[0].article_code == "123"
    assert "Điều 123" in response.final_answer
    assert response.clarification is None


def test_weak_token_overlap_does_not_guess_article(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.article_lookup.search_exact_articles", lambda _refs, _limit: [])
    monkeypatch.setattr(
        "app.services.article_lookup.search_fulltext",
        lambda _message, _limit: [
            {
                "article_code": "118",
                "title": "Tội phá rối an ninh",
                "score": 6.0,
                "source": "article_fulltext",
                "matched_terms": ["Tội phá rối an ninh"],
            }
        ],
    )

    response = handle_legal_chat("uống cà phê đi tù bao nhiêu năm")

    assert response.status == CaseStatus.answered
    assert response.candidate_articles == []
    assert response.clarification is None
    assert "chưa xác định được tội danh" in response.final_answer.lower()
