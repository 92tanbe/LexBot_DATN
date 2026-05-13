from __future__ import annotations

from pathlib import Path

from app.pipeline import pdf_textbook as pt


def test_split_articles_keeps_first_occurrence() -> None:
    sample = """
CHƯƠNG I PHẦN CHUNG

Điều 1. Mở đầu
Nội dung điều 1 ngắn.

Điều 123. Tội giết người
Nội dung quan trọng về Điều 123.

Điều 124. Tội khác
Kết thúc.
"""

    arts = pt.split_articles(sample)
    assert 123 in arts
    assert "Điều 123" in arts[123].body
    assert "Điều 124" not in arts[123].body.splitlines()[0]


def test_pdf_lookup_article(monkeypatch) -> None:
    sample = """

CHƯƠNG II

Điều 5. Thu thử
Đoạn trong điều 5."""

    monkeypatch.setattr(
        pt,
        "load_blhs_pdf_text",
        lambda: (sample.strip(), Path("dummy.pdf")),
    )

    resp = pt.run_pdf_lookup_pipeline("Nội dung Điều 5 là gì?", include_debug=False)
    assert resp.structured.get("type") == "pdf_lookup"
    assert resp.structured.get("matched_as") == "article"
    assert "Điều 5" in resp.final_answer
    assert resp.citations and resp.citations[0].article == 5


def test_pdf_lookup_rejects_off_topic(monkeypatch) -> None:
    def _boom() -> tuple[str, Path]:
        raise AssertionError("Không được đọc PDF khi câu không liên quan BLHS")

    monkeypatch.setattr(pt, "load_blhs_pdf_text", _boom)
    resp = pt.run_pdf_lookup_pipeline(
        "dự báo hôm nay có mưa, chả biết cậu có người yêu hay chưa",
        include_debug=False,
    )
    assert resp.structured.get("intent") == "out_of_scope"
    assert resp.structured.get("scope_gate") == "blhs_only"
    assert "Theo VB" not in resp.final_answer
    assert "trích trong file PDF" not in resp.final_answer


def test_pdf_lookup_rejects_money_bank_request(monkeypatch) -> None:
    def _boom() -> tuple[str, Path]:
        raise AssertionError("Không được đọc PDF khi câu chỉ đòi tiền / tài khoản")

    monkeypatch.setattr(pt, "load_blhs_pdf_text", _boom)
    resp = pt.run_pdf_lookup_pipeline("cho tôi 5 triệu vào tài khoản được", include_debug=False)
    assert resp.structured.get("intent") == "out_of_scope"
    assert "Điều 426" not in resp.final_answer


def test_pdf_lookup_keyword_when_article_missing(monkeypatch) -> None:
    sample = """

Điều 77. Thu thử
Đây có từ khóa hành hung cho tính điểm."""

    monkeypatch.setattr(
        pt,
        "load_blhs_pdf_text",
        lambda: (sample.strip(), Path("dummy.pdf")),
    )

    resp = pt.run_pdf_lookup_pipeline(
        "Hành hung người khác được quy định ở đâu?",
        include_debug=False,
    )
    assert resp.structured.get("matched_as") == "keyword_article"
    assert "Điều 77" in resp.final_answer
