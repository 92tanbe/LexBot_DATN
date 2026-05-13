"""Test post-processing validator (chong hallucination)."""
from __future__ import annotations

from unittest.mock import patch

from app.models.legal_output import (
    ActorAnalysis,
    CaseAnalysis,
    CitationOutput,
    HinhPhatOutput,
    ToiDanhOutput,
)
from app.postprocessing.validator import validate_case_analysis


def _make_case(article: int, clause: int | None, rule_id: str | None = None) -> CaseAnalysis:
    cit = CitationOutput(article=article, clause=clause, rule_id=rule_id)
    td = ToiDanhOutput(
        dieu=article,
        khoan=clause,
        ten_toi="Toi cuop tai san",
        vai_tro="chinh pham",
        hinh_phat=HinhPhatOutput(loai="tu", min=3, max=10, don_vi="nam"),
        citations=[cit] if rule_id else [],
    )
    actor = ActorAnalysis(name="A", vai_tro="chinh pham", toi_danh=[td])
    return CaseAnalysis(summary="Vu cuop", actors=[actor], confidence="high")


def test_validator_keep_when_known():
    case = _make_case(article=168, clause=2, rule_id="168_r2")
    case_out, warns = validate_case_analysis(
        case, known_articles={168}, known_rule_ids={"168_r2"}
    )
    assert case_out.actors[0].toi_danh[0].dieu == 168
    assert case_out.confidence == "high"


def test_validator_drop_unknown_article():
    case = _make_case(article=9999, clause=1)
    with patch(
        "app.postprocessing.validator._verify_articles_in_db", return_value={}
    ), patch("app.postprocessing.validator._verify_rule_ids_in_db", return_value={}):
        case_out, warns = validate_case_analysis(
            case, known_articles={168}, known_rule_ids=set()
        )
    assert all(td.dieu != 9999 for actor in case_out.actors for td in actor.toi_danh)
    assert case_out.confidence == "low"
    assert any("khong co trong context" in w for w in warns)


def test_validator_filter_invalid_citation():
    case = _make_case(article=168, clause=2, rule_id="FAKE_RULE")
    with patch(
        "app.postprocessing.validator._verify_articles_in_db",
        return_value={168: {"article": 168, "crime_id": "168", "dieu_name": "Toi cuop"}},
    ), patch("app.postprocessing.validator._verify_rule_ids_in_db", return_value={}):
        case_out, warns = validate_case_analysis(
            case, known_articles=set(), known_rule_ids=set()
        )
    cits = case_out.actors[0].toi_danh[0].citations
    assert all(c.rule_id != "FAKE_RULE" for c in cits)


def test_validator_no_actors_lowers_confidence():
    case = CaseAnalysis(summary="x", actors=[], confidence="high")
    case_out, warns = validate_case_analysis(case, known_articles=set(), known_rule_ids=set())
    assert case_out.confidence == "low"


def test_case_analysis_normalizes_accented_roles():
    case = CaseAnalysis.model_validate(
        {
            "summary": "Vu dong pham cuop tai san",
            "actors": [
                {
                    "name": "B",
                    "vai_tro": "đồng phạm",
                    "toi_danh": [
                        {
                            "dieu": 168,
                            "khoan": 2,
                            "ten_toi": "Toi cuop tai san",
                            "vai_tro": "đồng phạm",
                        }
                    ],
                }
            ],
            "confidence": "medium",
        }
    )

    assert case.actors[0].vai_tro == "dong pham"
    assert case.actors[0].toi_danh[0].vai_tro == "dong pham"


def test_case_analysis_accepts_victim_role():
    case = CaseAnalysis.model_validate(
        {
            "summary": "Bac si vo y lam benh nhan tu vong",
            "actors": [
                {"name": "E", "vai_tro": "chinh pham", "toi_danh": []},
                {"name": "F", "vai_tro": "nạn nhân", "toi_danh": []},
            ],
            "confidence": "medium",
        }
    )

    assert case.actors[1].vai_tro == "nan nhan"
