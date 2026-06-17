from __future__ import annotations


def build_context_text(contexts: list[dict], max_chars: int = 12000) -> str:
    chunks: list[str] = []
    for ctx in contexts:
        article = ctx.get("article") or {}
        crime = ctx.get("crime") or {}
        chunks.append(f"Điều {article.get('article_code')}: {article.get('title')}")
        if crime:
            chunks.append(f"Tội danh: {crime.get('name')}")
        for cl in (ctx.get("clauses") or [])[:8]:
            chunks.append(f"Khoản {cl.get('clause_no')}: {cl.get('text')}")
        for pt in (ctx.get("points") or [])[:8]:
            chunks.append(f"Điểm {pt.get('point_label') or pt.get('point')}: {pt.get('text')}")
        for cond in (ctx.get("conditions") or [])[:10]:
            chunks.append(f"Điều kiện [{cond.get('id')}]: {cond.get('text')}")
        for pf in (ctx.get("penalty_frames") or [])[:10]:
            chunks.append(f"Khung phạt [{pf.get('id')}]: {pf.get('text')}")
        for pen in (ctx.get("penalties") or [])[:10]:
            chunks.append(f"Hình phạt [{pen.get('id')}]: {pen.get('text')}")
    text = "\n".join(chunks)
    return text[:max_chars]


def citations_from_contexts(contexts: list[dict]) -> list[dict]:
    citations: list[dict] = []
    for ctx in contexts:
        article = ctx.get("article") or {}
        citations.append({"article_code": article.get("article_code"), "title": article.get("title")})
    return citations
