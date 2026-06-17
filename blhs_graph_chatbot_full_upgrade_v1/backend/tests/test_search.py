from app.services.rrf import reciprocal_rank_fusion
from app.routers.search import _enrich_candidates


def test_rrf_merges_by_article_code():
    fused = reciprocal_rank_fusion([
        [{"article_code": "12", "title": "A", "score": 2, "source": "x"}],
        [{"article_code": "12", "title": "A", "score": 1, "source": "y"}, {"article_code": "17", "title": "B", "score": 1, "source": "y"}],
    ])
    assert fused[0]["article_code"] == "12"
    assert "x" in fused[0]["sources"]
    assert "y" in fused[0]["sources"]


def test_search_candidates_include_article_title_and_content():
    candidates = [{"article_code": "249", "title": "Điều 249", "score": 1.0}]
    contexts = [{
        "article": {"article_code": "249", "title": "Tội tàng trữ trái phép chất ma túy"},
        "clauses": [{"clause_no": "1", "text": "Người nào tàng trữ trái phép chất ma túy..."}],
        "points": [{"point_label": "a", "text": "Có tổ chức."}],
    }]

    enriched = _enrich_candidates(candidates, contexts)

    assert enriched[0].article_title == "Tội tàng trữ trái phép chất ma túy"
    assert "Khoản 1" in (enriched[0].article_content or "")
    assert "Điểm a" in (enriched[0].article_content or "")
