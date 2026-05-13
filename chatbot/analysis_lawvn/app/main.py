"""FastAPI service entrypoint cho Chatbot RAG BLHS.

Chay (tu thu muc chatbot/):
    uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

Hoac tu repo root:
    uvicorn chatbot.app.main:app --port 8001
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.neo4j_driver import close_driver, get_driver
from app.routers import health, rag

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Khoi tao tai nguyen 1 lan luc khoi dong."""
    logger.info("==== Chatbot RAG BLHS khoi dong ====")
    logger.info("File .env da nap (neu co): %s", settings.env_file_path or "(khong tim thay)")
    logger.info("Embedding model: %s", settings.embedding_model)
    logger.info("Reranker enabled: %s", settings.enable_reranker)
    logger.info("OpenAI configured: %s", bool(settings.openai_api_key))
    logger.info("Neo4j URI: %s", settings.neo4j_uri)

    # Verify Neo4j connectivity som
    try:
        get_driver().verify_connectivity()
        logger.info("Neo4j ket noi OK")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Neo4j chua ket noi duoc: %s", exc)

    # Pre-warm embedding (khong block startup neu loi)
    try:
        from app.retrievers.embedding import get_embedding_model

        get_embedding_model()
        logger.info("Embedding model san sang")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Khong load duoc embedding model: %s", exc)

    if settings.enable_reranker:
        try:
            from app.retrievers.reranker import get_reranker

            get_reranker()
            logger.info("Reranker san sang")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reranker chua san sang: %s", exc)

    yield

    logger.info("==== Chatbot RAG BLHS tat ====")
    close_driver()


app = FastAPI(
    title="Chatbot RAG BLHS",
    version="0.1.0",
    description="Hybrid RAG cho Bo luat Hinh su Viet Nam (Neo4j + BKAI + GPT-4o-mini).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(rag.router)


@app.get("/")
def root() -> dict:
    return {
        "service": "chatbot-rag-blhs",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": ["/health", "/readyz", "/rag/query", "/rag/query/stream"],
        "chat_modes": [
            {"id": "tra_cuu_pdf", "desc": "Mac dinh: tra cuu VB PDF + chat nhanh (dataset / BLHS_PDF_PATH)."},
            {"id": "phan_tich", "desc": "Tuy chon: phan tinh Neo4j + Hybrid RAG + LLM."},
        ],
    }


def _run() -> None:
    """Helper de chay tu CLI: python -m app.main"""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    _run()
