"""Chunking + Embedding multi-level cho BLHS.

Quy trinh:
    1. Tao 2 vector index trong Neo4j (DieuLuat va QuyTac).
    2. Lay text cua DieuLuat va QuyTac da ton tai trong graph.
    3. Build chunk_text co cau truc cho 2 muc (coarse Dieu, fine Khoan).
    4. Embed batch bang BKAI bi-encoder.
    5. Ghi tro lai property `embedding`, `chunk_text`, `token_count` vao node.
    6. Smoke test query vector index.

Cach chay:
    cd <repo>
    python -m chatbot.ingestion.chunk_embed --level all
    python -m chatbot.ingestion.chunk_embed --level dieu --limit 50  # debug nhanh
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Cho phep chay python -m chatbot.ingestion.chunk_embed tu repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHATBOT_ROOT = Path(__file__).resolve().parents[1]
for _p in (_CHATBOT_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.core.config import settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.core.neo4j_driver import get_driver, close_driver, session_scope  # noqa: E402
from app.retrievers.embedding import embed_texts, get_embedding_dim, chunked  # noqa: E402

logger = logging.getLogger(__name__)


# ----------------------------- Vector index DDL -----------------------------

def _vector_index_ddl(name: str, label: str, dim: int) -> str:
    """Sinh cau lenh tao vector index. Cu phap Neo4j 5.13+."""
    return (
        f"CREATE VECTOR INDEX {name} IF NOT EXISTS "
        f"FOR (n:{label}) ON (n.embedding) "
        f"OPTIONS {{ indexConfig: {{ "
        f"`vector.dimensions`: {dim}, "
        f"`vector.similarity_function`: 'cosine' "
        f"}} }}"
    )


def ensure_vector_indexes(dim: int) -> None:
    """Tao vector index cho DieuLuat va QuyTac."""
    queries = [
        _vector_index_ddl(settings.dieu_vector_index, "DieuLuat", dim),
        _vector_index_ddl(settings.rule_vector_index, "QuyTac", dim),
    ]
    with session_scope() as sess:
        for q in queries:
            sess.run(q)
            logger.info("Da tao/da co vector index: %s", q.split(" FOR")[0])


# --------------------------- Lay du lieu tu Neo4j ---------------------------

DIEU_FETCH_QUERY = """
MATCH (d:DieuLuat)
OPTIONAL MATCH (d)<-[:CO_DIEU]-(c:Chuong)
OPTIONAL MATCH (c)-[:THUOC_NHOM]->(n:NhomToi)
OPTIONAL MATCH (d)-[:CO_QUY_TAC]->(r:QuyTac)
OPTIONAL MATCH (r)-[:CO_HINH_PHAT]->(hp:HinhPhat)
OPTIONAL MATCH (r)-[:CO_DIEU_KIEN]->(dk:DieuKien)
WITH d, c, n, r, hp, collect(DISTINCT dk.text) AS conditions
WITH d, c, n,
     collect(DISTINCT {
       clause: r.clause,
       logic: r.logic,
       priority: r.priority,
       conditions: conditions,
       penalty_min: hp.min,
       penalty_max: hp.max,
       penalty_extra: hp.extra,
       penalty_note: hp.note
     }) AS rules
RETURN d.crime_id  AS crime_id,
       d.article   AS article,
       d.name      AS name,
       d.chapter_id AS chapter_id,
       c.name      AS chuong_name,
       n.ten       AS nhom_toi,
       rules
ORDER BY toInteger(d.article)
"""


KHOAN_FETCH_QUERY = """
MATCH (d:DieuLuat)-[:CO_QUY_TAC]->(r:QuyTac)
OPTIONAL MATCH (r)-[:CO_DIEU_KIEN]->(dk:DieuKien)
OPTIONAL MATCH (r)-[:CO_HINH_PHAT]->(hp:HinhPhat)
WITH d, r, hp,
     collect(DISTINCT {type: dk.type, text: dk.text}) AS conditions
RETURN d.crime_id  AS crime_id,
       d.article   AS article,
       d.name      AS dieu_name,
       r.rule_id   AS rule_id,
       r.clause    AS clause,
       r.logic     AS logic,
       r.priority  AS priority,
       conditions,
       hp.min      AS penalty_min,
       hp.max      AS penalty_max,
       hp.extra    AS penalty_extra,
       hp.note     AS penalty_note,
       hp.fine     AS penalty_fine,
       hp.fine_min AS penalty_fine_min,
       hp.fine_max AS penalty_fine_max,
       hp.prison_min  AS penalty_prison_min,
       hp.prison_max  AS penalty_prison_max,
       hp.prison_unit AS penalty_prison_unit,
       hp.reform_min  AS penalty_reform_min,
       hp.reform_max  AS penalty_reform_max,
       hp.reform_unit AS penalty_reform_unit
ORDER BY toInteger(d.article), toInteger(coalesce(r.clause, 0))
"""


# --------------------------- Build chunk text -------------------------------

def _format_penalty(row: dict[str, Any]) -> str:
    """Format hình phạt thành chuỗi tiếng Việt có dấu (khớp với BKAI tokenizer)."""
    parts: list[str] = []
    if row.get("penalty_min") is not None and row.get("penalty_max") is not None:
        parts.append(f"phạt tù từ {row['penalty_min']} đến {row['penalty_max']} năm")
    elif row.get("penalty_min") is not None:
        parts.append(f"mức phạt từ {row['penalty_min']} năm")

    if row.get("penalty_prison_min") is not None and row.get("penalty_prison_max") is not None:
        unit = row.get("penalty_prison_unit") or "tháng"
        parts.append(
            f"tù từ {row['penalty_prison_min']} đến {row['penalty_prison_max']} {unit}"
        )
    if row.get("penalty_reform_min") is not None and row.get("penalty_reform_max") is not None:
        unit = row.get("penalty_reform_unit") or "năm"
        parts.append(
            f"cải tạo không giam giữ {row['penalty_reform_min']} đến {row['penalty_reform_max']} {unit}"
        )
    if row.get("penalty_fine_min") is not None and row.get("penalty_fine_max") is not None:
        parts.append(
            f"phạt tiền từ {row['penalty_fine_min']:,} đến {row['penalty_fine_max']:,} đồng"
        )
    elif row.get("penalty_fine") is not None:
        try:
            fine_val = int(row["penalty_fine"])
            parts.append(f"phạt tiền {fine_val:,} đồng")
        except (TypeError, ValueError):
            pass

    if row.get("penalty_extra"):
        parts.append(str(row["penalty_extra"]))
    if row.get("penalty_note"):
        parts.append(str(row["penalty_note"]))
    return "; ".join(parts) if parts else ""


_LOGIC_VI = {
    "BASE": "khung cơ bản",
    "AGGRAVATION": "tăng nặng",
    "AGGREGATION": "tổng hợp",
    "MITIGATION": "giảm nhẹ",
    "ACCOMPLICE": "đồng phạm",
    "ATTEMPT": "phạm tội chưa đạt",
    "PREPARATION": "chuẩn bị phạm tội",
    "ADDITIONAL_PENALTY": "hình phạt bổ sung",
}


def _vi_logic(code: str | None) -> str:
    if not code:
        return ""
    return _LOGIC_VI.get(code.upper(), code)


def build_dieu_chunk_text(record: dict[str, Any]) -> str:
    """Chunk Điều luật (coarse): tóm tắt cả Điều, dùng tiếng Việt có dấu."""
    article = record.get("article")
    name = record.get("name") or ""
    chuong = record.get("chuong_name") or ""
    nhom = record.get("nhom_toi") or ""

    lines: list[str] = []
    lines.append(f"Điều {article}. {name}".strip())
    if chuong:
        lines.append(f"Chương: {chuong}")
    if nhom and nhom != chuong:
        lines.append(f"Nhóm tội: {nhom}")

    rules = record.get("rules") or []
    base_rules = [r for r in rules if (r.get("logic") or "").upper() == "BASE"]
    target_rules = base_rules or rules
    for r in sorted(target_rules, key=lambda x: (x.get("priority") or 99, x.get("clause") or 99)):
        clause = r.get("clause")
        logic_vi = _vi_logic(r.get("logic"))
        conds = [c for c in (r.get("conditions") or []) if c]
        cond_str = "; ".join(conds[:6])
        penalty_str = _format_penalty(r)
        head = f"  Khoản {clause}" if clause else "  Khoản ?"
        if logic_vi:
            head += f" ({logic_vi})"
        head += ":"
        if cond_str:
            head += f" {cond_str}."
        if penalty_str:
            head += f" Hình phạt: {penalty_str}."
        lines.append(head)

    return "\n".join(lines).strip()


def build_khoan_chunk_text(record: dict[str, Any]) -> str:
    """Chunk Khoản (fine): chi tiết 1 quy tắc, dùng tiếng Việt có dấu."""
    article = record.get("article")
    dieu_name = record.get("dieu_name") or ""
    clause = record.get("clause")
    logic_vi = _vi_logic(record.get("logic"))

    head = f"Điều {article} khoản {clause}".strip() if clause else f"Điều {article}"
    if logic_vi:
        head += f" ({logic_vi})"
    head += f" - {dieu_name}".rstrip(" -")

    lines = [head]
    conds = record.get("conditions") or []
    cond_texts: list[str] = []
    role_texts: list[str] = []
    aggrav_texts: list[str] = []
    mitigate_texts: list[str] = []
    for c in conds:
        if not c or not c.get("text"):
            continue
        ctype = (c.get("type") or "").lower()
        text = c["text"].strip()
        if ctype in {"role", "actor", "subject"}:
            role_texts.append(text)
        elif ctype in {"aggravating", "aggravating_circumstance"}:
            aggrav_texts.append(text)
        elif ctype in {"mitigating"}:
            mitigate_texts.append(text)
        else:
            cond_texts.append(text)

    if role_texts:
        lines.append("Vai trò/Đối tượng: " + "; ".join(role_texts))
    if cond_texts:
        lines.append("Điều kiện: " + "; ".join(cond_texts))
    if aggrav_texts:
        lines.append("Tình tiết tăng nặng: " + "; ".join(aggrav_texts))
    if mitigate_texts:
        lines.append("Tình tiết giảm nhẹ: " + "; ".join(mitigate_texts))

    penalty_str = _format_penalty(record)
    if penalty_str:
        lines.append("Hình phạt: " + penalty_str)

    return "\n".join(lines).strip()


# ------------------------------ Token estimate ------------------------------

def _estimate_tokens(text: str) -> int:
    """Uoc luong so token (~ 1 token / 4 ky tu cho VN)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# ------------------------------ Write to Neo4j ------------------------------

WRITE_DIEU_QUERY = """
UNWIND $rows AS row
MATCH (d:DieuLuat {crime_id: row.crime_id})
SET d.chunk_text = row.chunk_text,
    d.chunk_token_count = row.token_count,
    d.embedding = row.embedding,
    d.embedded_at = datetime()
"""

WRITE_KHOAN_QUERY = """
UNWIND $rows AS row
MATCH (r:QuyTac {rule_id: row.rule_id})
SET r.chunk_text = row.chunk_text,
    r.chunk_token_count = row.token_count,
    r.embedding = row.embedding,
    r.embedded_at = datetime()
"""


# --------------------------------- Pipeline ---------------------------------

def fetch_records(query: str, limit: int | None = None) -> list[dict[str, Any]]:
    with session_scope() as sess:
        cypher = query
        params: dict[str, Any] = {}
        if limit:
            cypher = query.rstrip()
            cypher += f"\nLIMIT {int(limit)}"
        return [record.data() for record in sess.run(cypher, **params)]


def ingest_level_dieu(limit: int | None = None) -> int:
    logger.info("Lay du lieu DieuLuat tu Neo4j...")
    records = fetch_records(DIEU_FETCH_QUERY, limit=limit)
    if not records:
        logger.warning("Khong co DieuLuat nao trong DB")
        return 0
    logger.info("Tong so DieuLuat: %d", len(records))

    rows: list[dict[str, Any]] = []
    chunk_texts: list[str] = []
    for rec in records:
        text = build_dieu_chunk_text(rec)
        rows.append({
            "crime_id": rec["crime_id"],
            "chunk_text": text,
            "token_count": _estimate_tokens(text),
        })
        chunk_texts.append(text)

    logger.info("Embedding %d DieuLuat...", len(chunk_texts))
    t0 = time.time()
    embeddings = embed_texts(chunk_texts, show_progress=True)
    logger.info("Embedding xong sau %.1fs", time.time() - t0)

    for row, emb in zip(rows, embeddings):
        row["embedding"] = emb.tolist()

    with session_scope() as sess:
        for batch in chunked(rows, 100):
            sess.run(WRITE_DIEU_QUERY, rows=batch)
    logger.info("Da ghi embedding cho %d DieuLuat", len(rows))
    return len(rows)


def ingest_level_khoan(limit: int | None = None) -> int:
    logger.info("Lay du lieu QuyTac tu Neo4j...")
    records = fetch_records(KHOAN_FETCH_QUERY, limit=limit)
    if not records:
        logger.warning("Khong co QuyTac nao trong DB")
        return 0
    logger.info("Tong so QuyTac: %d", len(records))

    rows: list[dict[str, Any]] = []
    chunk_texts: list[str] = []
    for rec in records:
        text = build_khoan_chunk_text(rec)
        rows.append({
            "rule_id": rec["rule_id"],
            "chunk_text": text,
            "token_count": _estimate_tokens(text),
        })
        chunk_texts.append(text)

    logger.info("Embedding %d QuyTac...", len(chunk_texts))
    t0 = time.time()
    embeddings = embed_texts(chunk_texts, show_progress=True)
    logger.info("Embedding xong sau %.1fs", time.time() - t0)

    for row, emb in zip(rows, embeddings):
        row["embedding"] = emb.tolist()

    with session_scope() as sess:
        for batch in chunked(rows, 100):
            sess.run(WRITE_KHOAN_QUERY, rows=batch)
    logger.info("Da ghi embedding cho %d QuyTac", len(rows))
    return len(rows)


# ------------------------------ Smoke test ----------------------------------

SMOKE_QUERY_DIEU = """
CALL db.index.vector.queryNodes($index, $top_k, $query_emb)
YIELD node, score
RETURN node.article AS article, node.name AS name, score
ORDER BY score DESC
"""

SMOKE_QUERY_RULE = """
CALL db.index.vector.queryNodes($index, $top_k, $query_emb)
YIELD node, score
RETURN node.rule_id AS rule_id, node.crime_id AS crime_id, score
ORDER BY score DESC
"""


def smoke_test(query: str = "cướp tài sản có vũ khí", top_k: int = 5) -> None:
    """Goi vector search bang query mau de xac nhan index OK."""
    from app.retrievers.embedding import embed_query

    logger.info("Smoke test voi query: %s", query)
    q_emb = embed_query(query)

    with session_scope() as sess:
        res_dieu = sess.run(
            SMOKE_QUERY_DIEU,
            index=settings.dieu_vector_index,
            top_k=top_k,
            query_emb=q_emb,
        ).data()
        logger.info("Top %d DieuLuat:", top_k)
        for r in res_dieu:
            logger.info("  - Dieu %s | %s | score=%.3f", r["article"], r["name"], r["score"])

        res_rule = sess.run(
            SMOKE_QUERY_RULE,
            index=settings.rule_vector_index,
            top_k=top_k,
            query_emb=q_emb,
        ).data()
        logger.info("Top %d QuyTac:", top_k)
        for r in res_rule:
            logger.info(
                "  - rule_id=%s crime_id=%s score=%.3f",
                r["rule_id"], r["crime_id"], r["score"],
            )


# --------------------------------- CLI -------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk + Embed BLHS vao Neo4j")
    parser.add_argument(
        "--level",
        choices=["dieu", "khoan", "all"],
        default="all",
        help="Muc do chunking can chay",
    )
    parser.add_argument("--limit", type=int, default=None, help="Gioi han so luong (debug)")
    parser.add_argument("--no-index", action="store_true", help="Bo qua tao vector index")
    parser.add_argument("--smoke", action="store_true", help="Chay smoke test sau khi ingest")
    parser.add_argument("--smoke-query", default="cướp tài sản có vũ khí")
    args = parser.parse_args()

    setup_logging()

    if not settings.neo4j_password:
        logger.error("Thieu NEO4J_PASSWORD trong .env, vui long kiem tra chatbot/.env")
        sys.exit(2)

    dim = get_embedding_dim()
    logger.info("Embedding model dim = %d", dim)

    if not args.no_index:
        ensure_vector_indexes(dim)

    try:
        if args.level in ("dieu", "all"):
            ingest_level_dieu(limit=args.limit)
        if args.level in ("khoan", "all"):
            ingest_level_khoan(limit=args.limit)

        if args.smoke:
            smoke_test(query=args.smoke_query)
    finally:
        close_driver()


if __name__ == "__main__":
    main()
