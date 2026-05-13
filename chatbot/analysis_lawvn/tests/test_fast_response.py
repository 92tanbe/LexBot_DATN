from __future__ import annotations

from app.pipeline.fast_response import build_fast_response, detect_fast_intent


def test_fast_response_handles_greeting() -> None:
    resp = build_fast_response("Xin chào", include_debug=True)

    assert resp is not None
    assert resp.structured["intent"] == "greeting"
    assert resp.confidence == "high"
    assert resp.citations == []
    assert resp.debug is not None
    assert "fast_path_ms" in resp.debug.timings_ms


def test_fast_response_greeting_loose_with_honorific() -> None:
    """Chao + xung ho (vi du 'cau') phai vao fast path, khong di tim PDF."""
    resp = build_fast_response("xin chào cậu")

    assert resp is not None
    assert resp.structured["intent"] == "greeting"
    assert "Chào bạn" in resp.final_answer
    # Khong phai loi tra loi trich dieu khoan tu PDF
    assert "Điều " not in resp.final_answer
    assert "theo VB" not in resp.final_answer


def test_fast_response_handles_out_of_scope_short_question() -> None:
    resp = build_fast_response("Thời tiết hôm nay thế nào?")

    assert resp is not None
    assert resp.structured["intent"] == "out_of_scope"
    assert "BLHS" in resp.final_answer
    assert "phân tích" in resp.final_answer.lower()
    assert "tôi sẽ giúp" in resp.final_answer.lower()
    assert "né nhẹ" in resp.final_answer.lower() or "kính BLHS" in resp.final_answer


def test_fast_response_does_not_treat_toi_as_crime_word() -> None:
    resp = build_fast_response("Tôi muốn hỏi thời tiết hôm nay")

    assert resp is not None
    assert resp.structured["intent"] == "out_of_scope"


def test_fast_response_does_not_intercept_legal_question() -> None:
    assert detect_fast_intent("Hành vi trên thuộc tội gì?") is None
    assert build_fast_response("A cướp tài sản 100 triệu thì phạm tội gì?") is None


def test_fast_response_rejects_social_weather_chat() -> None:
    resp = build_fast_response(
        "dự báo hôm nay có mưa, chả biết cậu có người yêu hay chưa",
    )
    assert resp is not None
    assert resp.structured["intent"] == "out_of_scope"
    assert "bạn cần hỗ trợ" in resp.final_answer.lower()


def test_fast_response_blocks_money_transfer_like_request() -> None:
    resp = build_fast_response("cho tôi 5 triệu vào tài khoản được")
    assert resp is not None
    assert resp.structured["intent"] == "out_of_scope"
    assert "đeo kính BLHS" in resp.final_answer or "BLHS" in resp.final_answer


def test_fast_response_keeps_dieu_khoan_phrase_as_in_scope() -> None:
    """Cum dieu+khoan (khong nham voi tu khoan trong tai khoan ngan hang)."""
    question = "Tôi có vướng điều khoản nào của luật hình sự không?"
    assert detect_fast_intent(question) is None
    assert build_fast_response(question) is None
