from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.graph_retriever import fetch_context_by_article

router = APIRouter(tags=["articles"])


@router.get("/articles/{article_code}")
def get_article(article_code: str) -> dict:
    ctx = fetch_context_by_article(article_code)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Article {article_code} not found")
    return ctx
