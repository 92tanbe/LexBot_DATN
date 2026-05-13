"""Test chuan hoa vai_tro (ASCII, nan nhan, ...) truoc khi validate CaseAnalysis."""
from __future__ import annotations

from app.models.legal_output import CaseAnalysis, normalize_vai_tro_value


def test_normalize_vai_tro_strips_vietnamese_accents() -> None:
    assert normalize_vai_tro_value("chính phạm") == "chinh pham"
    assert normalize_vai_tro_value("Đồng phạm") == "dong pham"


def test_normalize_vai_tro_accepts_nan_nhan() -> None:
    assert normalize_vai_tro_value("nan nhan") == "nan nhan"
    assert normalize_vai_tro_value("nạn nhân") == "nan nhan"


def test_case_analysis_accepts_accented_literals() -> None:
    case = CaseAnalysis.model_validate(
        {
            "summary": "Thử nghiệm schema",
            "actors": [
                {
                    "name": "B",
                    "vai_tro": "chính phạm",
                    "toi_danh": [
                        {
                            "dieu": 168,
                            "khoan": 1,
                            "ten_toi": "Tội cướp tài sản",
                            "vai_tro": "chính phạm",
                            "citations": [{"article": 168, "clause": 1, "rule_id": "168_r1"}],
                        }
                    ],
                    "nhan_xet": "",
                },
                {
                    "name": "H",
                    "vai_tro": "nạn nhân",
                    "toi_danh": [],
                },
            ],
            "confidence": "high",
        }
    )
    assert case.actors[0].vai_tro == "chinh pham"
    assert case.actors[0].toi_danh[0].vai_tro == "chinh pham"
    assert case.actors[1].vai_tro == "nan nhan"


def test_property_violence_hint_detects_robbery_scenario() -> None:
    from app.pipeline.orchestrator import _property_violence_article_candidates

    q = (
        "B thay chi H deo hai nhan vang o ngon tay nen B dung gay danh vao sau gay "
        "lam chi H ngat, sau do B lay hai chiec nhan vang cua chi H"
    )
    arts = _property_violence_article_candidates(q)
    assert 168 in arts
