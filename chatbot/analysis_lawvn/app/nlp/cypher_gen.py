"""Cypher generator co kiem soat (template + few-shot LLM fallback).

Quy tac an toan:
- Chi cho phep label/relationship trong WHITELIST.
- Mac dinh dung cac template co san; chi rot xuong LLM khi co flag explicit.
- Moi cypher do LLM sinh deu duoc validate truoc khi chay.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.nlp.ner import CaseEntities

logger = logging.getLogger(__name__)


# Whitelist node label / relationship type duoc phep xuat hien trong cypher.
ALLOWED_LABELS: set[str] = {
    "Phan",
    "Chuong",
    "DieuLuat",
    "QuyTac",
    "DieuKien",
    "HinhPhat",
    "VaiTro",
    "TinhTiet",
    "NhomToi",
}

ALLOWED_RELATIONSHIPS: set[str] = {
    "CO_CHUONG",
    "CO_DIEU",
    "CO_QUY_TAC",
    "CO_DIEU_KIEN",
    "CO_HINH_PHAT",
    "LIEN_QUAN",
    "LA_VAI_TRO",
    "LA_TINH_TIET",
    "THUOC_NHOM",
}

FORBIDDEN_KEYWORDS = {
    "create",
    "merge",
    "delete",
    "remove",
    "set",
    "drop",
    "load",
    "csv",
    "call dbms",
    "apoc.cypher.runschema",
}


@dataclass
class CypherCandidate:
    """1 cau Cypher de chay + ten template + params."""

    name: str
    cypher: str
    params: dict[str, Any]


# --------------------- Template Cypher cho cac y dinh -----------------------

TEMPLATE_BY_ARTICLE = """
MATCH (d:DieuLuat) WHERE toInteger(d.article) = $article
OPTIONAL MATCH (d)-[:CO_QUY_TAC]->(r:QuyTac)
OPTIONAL MATCH (r)-[:CO_HINH_PHAT]->(hp:HinhPhat)
OPTIONAL MATCH (r)-[:CO_DIEU_KIEN]->(dk:DieuKien)
RETURN d.article AS article, d.name AS dieu_name,
       r.clause AS clause, r.logic AS logic, r.chunk_text AS rule_text,
       collect(DISTINCT dk.text) AS conditions,
       hp.min AS hp_min, hp.max AS hp_max, hp.extra AS hp_extra
ORDER BY toInteger(coalesce(r.clause, 0))
""".strip()

TEMPLATE_BY_CRIME_NAME = """
CALL db.index.fulltext.queryNodes('dieu_name_search', $keyword)
YIELD node AS d, score
OPTIONAL MATCH (d)-[:CO_QUY_TAC]->(r:QuyTac {logic: 'BASE'})
OPTIONAL MATCH (r)-[:CO_HINH_PHAT]->(hp:HinhPhat)
RETURN d.article AS article, d.name AS dieu_name, score,
       r.clause AS clause, hp.min AS hp_min, hp.max AS hp_max, hp.extra AS hp_extra
ORDER BY score DESC LIMIT 5
""".strip()

TEMPLATE_BY_ROLE = """
MATCH (v:VaiTro) WHERE toLower(v.ten) CONTAINS toLower($role)
MATCH (dk:DieuKien)-[:LA_VAI_TRO]->(v)
MATCH (r:QuyTac {rule_id: dk.rule_id})
OPTIONAL MATCH (d:DieuLuat {crime_id: r.crime_id})
RETURN d.article AS article, d.name AS dieu_name,
       r.clause AS clause, v.ten AS vai_tro, dk.text AS dk_text
LIMIT 20
""".strip()

TEMPLATE_AGGRAVATING = """
MATCH (d:DieuLuat) WHERE toInteger(d.article) = $article
MATCH (d)-[:CO_QUY_TAC]->(r:QuyTac) WHERE r.logic IN ['AGGRAVATION', 'AGGREGATION']
MATCH (r)-[:CO_DIEU_KIEN]->(dk:DieuKien)
OPTIONAL MATCH (r)-[:CO_HINH_PHAT]->(hp:HinhPhat)
RETURN d.article AS article, d.name AS dieu_name,
       r.clause AS clause, collect(DISTINCT dk.text) AS conditions,
       hp.min AS hp_min, hp.max AS hp_max
ORDER BY toInteger(coalesce(r.clause, 0))
""".strip()

TEMPLATE_BY_AMOUNT = """
CALL db.index.fulltext.queryNodes('dk_text_search', $keyword)
YIELD node AS dk, score
MATCH (r:QuyTac {rule_id: dk.rule_id})-[:CO_HINH_PHAT]->(hp:HinhPhat)
OPTIONAL MATCH (d:DieuLuat {crime_id: r.crime_id})
RETURN d.article AS article, d.name AS dieu_name, r.clause AS clause,
       dk.text AS dk_text, hp.min AS hp_min, hp.max AS hp_max, score
ORDER BY score DESC LIMIT 10
""".strip()

TEMPLATE_LIEN_QUAN = """
MATCH (d:DieuLuat) WHERE toInteger(d.article) = $article
MATCH (d)-[:LIEN_QUAN]->(d2:DieuLuat)
RETURN d2.article AS article, d2.name AS dieu_name LIMIT 10
""".strip()


# ----------------------- Cypher safety validation --------------------------


def _strip_cypher_comments(cypher: str) -> str:
    cypher = re.sub(r"//.*", "", cypher)
    cypher = re.sub(r"/\*.*?\*/", "", cypher, flags=re.DOTALL)
    return cypher


def is_safe_cypher(cypher: str) -> tuple[bool, str]:
    """Validate cypher: chi cho phep READ, label/rel trong whitelist."""
    if not cypher:
        return False, "empty cypher"
    body = _strip_cypher_comments(cypher).lower()

    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", body):
            return False, f"chua tu khoa cam: {kw}"

    for label in re.findall(r":\s*([A-Z][A-Za-z0-9_]*)", cypher):
        if label not in ALLOWED_LABELS and label not in ALLOWED_RELATIONSHIPS:
            return False, f"label/rel khong duoc phep: {label}"

    return True, "ok"


# ------------------------- Generator chinh ---------------------------------


def generate_candidates(question: str, entities: CaseEntities) -> list[CypherCandidate]:
    """Sinh danh sach Cypher dua tren entities da trich.

    Tra ve list[CypherCandidate], orchestrator se chay lan luot cau toi
    duoc khi can graph results bo sung cho context.
    """
    candidates: list[CypherCandidate] = []

    # 1. Article refs explicit
    for ref in entities.article_refs:
        candidates.append(
            CypherCandidate(
                name="by_article",
                cypher=TEMPLATE_BY_ARTICLE,
                params={"article": int(ref.article)},
            )
        )
        candidates.append(
            CypherCandidate(
                name="lien_quan",
                cypher=TEMPLATE_LIEN_QUAN,
                params={"article": int(ref.article)},
            )
        )

    # 2. Crime hints -> fulltext theo ten
    for hint in entities.crime_hints[:3]:
        if not hint:
            continue
        candidates.append(
            CypherCandidate(
                name="by_crime_name",
                cypher=TEMPLATE_BY_CRIME_NAME,
                params={"keyword": hint},
            )
        )

    # 3. Roles -> graph theo VaiTro
    for role in entities.roles[:3]:
        if not role:
            continue
        candidates.append(
            CypherCandidate(
                name="by_role",
                cypher=TEMPLATE_BY_ROLE,
                params={"role": role},
            )
        )

    # 4. Amount -> fulltext dieu kien (re-use khoa)
    if entities.amounts:
        kw_parts: list[str] = []
        for amt in entities.amounts:
            if amt.unit == "dong":
                if amt.value >= 1_000_000_000:
                    kw_parts.append(f"{int(amt.value/1_000_000_000)} ty")
                elif amt.value >= 1_000_000:
                    kw_parts.append(f"{int(amt.value/1_000_000)} trieu")
            elif amt.unit == "nguoi":
                kw_parts.append(f"{int(amt.value)} nguoi")
            elif amt.unit == "percent":
                kw_parts.append(f"{int(amt.value)}%")
        if kw_parts:
            candidates.append(
                CypherCandidate(
                    name="by_amount",
                    cypher=TEMPLATE_BY_AMOUNT,
                    params={"keyword": " ".join(kw_parts[:3])},
                )
            )

    # 5. Aggravating cho dieu da xac dinh
    for ref in entities.article_refs:
        candidates.append(
            CypherCandidate(
                name="aggravating",
                cypher=TEMPLATE_AGGRAVATING,
                params={"article": int(ref.article)},
            )
        )

    # Validate hau cung
    safe = []
    for cand in candidates:
        ok, msg = is_safe_cypher(cand.cypher)
        if not ok:
            logger.warning("Bo qua cypher %s vi khong an toan: %s", cand.name, msg)
            continue
        safe.append(cand)
    return safe


def execute_candidates(
    candidates: list[CypherCandidate], max_run: int = 6
) -> list[dict[str, Any]]:
    """Chay tuan tu cac candidate, tra ve list ket qua thuan."""
    from app.core.neo4j_driver import session_scope

    results: list[dict[str, Any]] = []
    if not candidates:
        return results

    with session_scope() as sess:
        for cand in candidates[:max_run]:
            try:
                rows = [r.data() for r in sess.run(cand.cypher, **cand.params)]
                results.append(
                    {"name": cand.name, "params": cand.params, "rows": rows}
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Cypher %s loi: %s", cand.name, exc)
    return results


# Marker giu API: settings dung cho whitelist (vd: extend qua env neu can)
__all__ = [
    "CypherCandidate",
    "generate_candidates",
    "execute_candidates",
    "is_safe_cypher",
]
