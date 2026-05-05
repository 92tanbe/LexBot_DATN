"""Validator cho CaseAnalysis: chong hallucination, kiem chung citation.

Tieu chi kiem tra:
1. Moi `dieu` trong toi_danh phai ton tai trong known_articles HOAC trong DB Neo4j.
2. Moi `rule_id` neu co phai nam trong known_rule_ids HOAC ton tai trong Neo4j.
3. Loai bo citation co rule_id sai, neu citation rong -> bo sung tu DB.
4. Neu nhieu loi -> ha confidence xuong "low" + ghi warnings.
"""
from __future__ import annotations

import logging
from typing import Iterable

from app.core.neo4j_driver import session_scope
from app.models.legal_output import CaseAnalysis, CitationOutput, ToiDanhOutput

logger = logging.getLogger(__name__)


CHECK_ARTICLES_QUERY = """
UNWIND $articles AS art
MATCH (d:DieuLuat) WHERE toInteger(d.article) = toInteger(art)
RETURN toInteger(d.article) AS article, d.crime_id AS crime_id, d.name AS dieu_name
"""

CHECK_RULES_QUERY = """
UNWIND $rule_ids AS rid
MATCH (r:QuyTac {rule_id: rid})
OPTIONAL MATCH (d:DieuLuat {crime_id: r.crime_id})
RETURN r.rule_id AS rule_id, r.clause AS clause,
       d.article AS article, d.name AS dieu_name
"""


def _verify_articles_in_db(articles: Iterable[int]) -> dict[int, dict]:
    arts = sorted({int(a) for a in articles if a is not None})
    if not arts:
        return {}
    try:
        with session_scope() as sess:
            records = sess.run(CHECK_ARTICLES_QUERY, articles=arts).data()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Verify articles loi: %s", exc)
        return {}
    return {r["article"]: r for r in records if r.get("article") is not None}


def _verify_rule_ids_in_db(rule_ids: Iterable[str]) -> dict[str, dict]:
    rids = list({r for r in rule_ids if r})
    if not rids:
        return {}
    try:
        with session_scope() as sess:
            records = sess.run(CHECK_RULES_QUERY, rule_ids=rids).data()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Verify rule_ids loi: %s", exc)
        return {}
    return {r["rule_id"]: r for r in records if r.get("rule_id")}


def _filter_citations(
    cits: list[CitationOutput],
    known_rule_ids: set[str],
    valid_articles: set[int],
    valid_rules_db: dict[str, dict],
) -> tuple[list[CitationOutput], list[str]]:
    """Loc citation, tra ve (filtered, warnings).

    Quy tac chat che:
    - Neu citation co rule_id ma rule_id khong hop le -> bo citation do (du article co the dung).
    - Neu khong co rule_id, citation chi giu duoc khi article ton tai trong context/DB.
    """
    out: list[CitationOutput] = []
    warns: list[str] = []
    for c in cits:
        if c.rule_id:
            if c.rule_id in known_rule_ids or c.rule_id in valid_rules_db:
                out.append(c)
            else:
                warns.append(
                    f"Bo citation khong khop: article={c.article} clause={c.clause} rule_id={c.rule_id}"
                )
        elif c.article in valid_articles:
            out.append(c)
        else:
            warns.append(
                f"Bo citation khong khop: article={c.article} clause={c.clause} rule_id={c.rule_id}"
            )
    return out, warns


def _ensure_citation(
    td: ToiDanhOutput,
    valid_articles: set[int],
    valid_rules_db: dict[str, dict],
) -> list[str]:
    """Neu toi_danh khong co citation hop le, them 1 citation tu DB neu co the."""
    if td.citations:
        return []
    warns: list[str] = []
    if td.dieu in valid_articles:
        td.citations.append(CitationOutput(article=td.dieu, clause=td.khoan))
    else:
        warns.append(f"Toi danh Dieu {td.dieu} khoan {td.khoan} thieu citation hop le")
    return warns


def validate_case_analysis(
    case: CaseAnalysis,
    known_articles: set[int] | None = None,
    known_rule_ids: set[str] | None = None,
) -> tuple[CaseAnalysis, list[str]]:
    """Validate CaseAnalysis. Tra ve (case_da_chinh_sua, warnings)."""
    known_articles = known_articles or set()
    known_rule_ids = known_rule_ids or set()
    warnings: list[str] = list(case.warnings or [])

    # Lay tat ca article & rule_id can verify
    all_articles = set()
    all_rule_ids = set()
    for actor in case.actors:
        for td in actor.toi_danh:
            if td.dieu:
                all_articles.add(int(td.dieu))
            for c in td.citations:
                if c.article:
                    all_articles.add(int(c.article))
                if c.rule_id:
                    all_rule_ids.add(c.rule_id)

    # Bo sung verify tu DB neu khong nam trong known_*
    extra_articles = sorted(a for a in all_articles if a not in known_articles)
    extra_rules = [r for r in all_rule_ids if r not in known_rule_ids]
    db_articles = _verify_articles_in_db(extra_articles) if extra_articles else {}
    db_rules = _verify_rule_ids_in_db(extra_rules) if extra_rules else {}

    valid_articles = set(known_articles) | set(db_articles.keys())
    valid_rule_ids = set(known_rule_ids) | set(db_rules.keys())

    # Loc va sua tung toi_danh
    invalid_count = 0
    for actor in case.actors:
        kept_td: list[ToiDanhOutput] = []
        for td in actor.toi_danh:
            if td.dieu and td.dieu not in valid_articles:
                warnings.append(
                    f"Toi danh Dieu {td.dieu} khoan {td.khoan} khong co trong context/DB - bo qua"
                )
                invalid_count += 1
                continue
            filtered_cits, cit_warns = _filter_citations(
                td.citations, valid_rule_ids, valid_articles, db_rules
            )
            td.citations = filtered_cits
            warnings.extend(cit_warns)
            warnings.extend(_ensure_citation(td, valid_articles, db_rules))
            kept_td.append(td)
        actor.toi_danh = kept_td

    # Ha confidence khi co loi
    if invalid_count > 0 or any("khong khop" in w for w in warnings):
        if case.confidence != "low":
            case.confidence = "low"
            warnings.append("Ha do tin cay xuong 'low' do thieu can cu phap ly")

    if not any(actor.toi_danh for actor in case.actors):
        if case.confidence != "low":
            case.confidence = "low"
        warnings.append("Khong co toi danh nao co citation hop le")

    case.warnings = warnings
    return case, warnings
