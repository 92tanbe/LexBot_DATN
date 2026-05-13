"""Tao context cho LLM tu danh sach RetrievedChunk + ket qua graph (cypher).

Format chuan:
    [Dieu X khoan Y - <ten toi>] (rule_id=...)
    <chunk_text>

Bao dam co dinh danh (article, clause, rule_id) trong moi block de
LLM citation chinh xac.
"""
from __future__ import annotations

import logging
from typing import Iterable

from app.models.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


def _format_chunk(c: RetrievedChunk, idx: int) -> str:
    head_parts: list[str] = [f"[#{idx}]"]
    if c.article is not None:
        if c.clause is not None:
            head_parts.append(f"Dieu {c.article} khoan {c.clause}")
        else:
            head_parts.append(f"Dieu {c.article}")
    if c.dieu_name:
        head_parts.append(f"- {c.dieu_name}")
    if c.logic:
        head_parts.append(f"({c.logic})")
    if c.rule_id:
        head_parts.append(f"rule_id={c.rule_id}")

    head = " ".join(head_parts)
    body = (c.text or "").strip()
    return f"{head}\n{body}"


def build_context(
    chunks: Iterable[RetrievedChunk],
    graph_results: list[dict] | None = None,
    max_chars: int = 12000,
) -> str:
    """Build context string truyen vao LLM."""
    blocks: list[str] = []
    total = 0
    for idx, c in enumerate(chunks, start=1):
        block = _format_chunk(c, idx)
        if total + len(block) > max_chars:
            blocks.append("[... bi cat do qua dai ...]")
            break
        blocks.append(block)
        total += len(block) + 2

    if graph_results:
        blocks.append("\n--- Graph results ---")
        for gr in graph_results[:5]:
            name = gr.get("name", "?")
            rows = gr.get("rows") or []
            blocks.append(f"[graph:{name}] {len(rows)} rows")
            for row in rows[:5]:
                line_parts = []
                if "article" in row:
                    line_parts.append(f"Dieu {row['article']}")
                if "clause" in row and row["clause"] is not None:
                    line_parts.append(f"khoan {row['clause']}")
                if "dieu_name" in row and row["dieu_name"]:
                    line_parts.append(f"- {row['dieu_name']}")
                if "hp_min" in row and row["hp_min"] is not None:
                    line_parts.append(f"hp={row['hp_min']}-{row.get('hp_max')}")
                if line_parts:
                    blocks.append("  " + " ".join(str(p) for p in line_parts))

    return "\n\n".join(blocks)


def collect_known_articles(chunks: Iterable[RetrievedChunk]) -> set[int]:
    """Tap article xuat hien trong context, dung de validator."""
    return {c.article for c in chunks if c.article is not None}


def collect_known_rule_ids(chunks: Iterable[RetrievedChunk]) -> set[str]:
    """Tap rule_id xuat hien trong context."""
    return {c.rule_id for c in chunks if c.rule_id}
