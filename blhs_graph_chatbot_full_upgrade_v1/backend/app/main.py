from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.neo4j import neo4j_db
from app.routers import agentic_rag, articles, chat, health, search
from app.services.reranker import warmup_reranker_model
from app.services.vector_retriever import warmup_embedding_model

STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)


def warmup_backend() -> dict[str, bool]:
    status = {
        "neo4j": False,
        "indexes": False,
        "embedding_model": False,
        "reranker_model": False,
    }

    try:
        status["neo4j"] = neo4j_db.verify()
        logger.info("Neo4j connection warmed up")
    except Exception as exc:
        logger.warning("Neo4j warmup failed: %s", exc)

    try:
        neo4j_db.ensure_indexes()
        status["indexes"] = True
        logger.info("Neo4j indexes ensured")
    except Exception as exc:
        logger.warning("Neo4j index warmup failed: %s", exc)

    status["embedding_model"] = warmup_embedding_model()
    status["reranker_model"] = warmup_reranker_model()
    logger.info("Backend warmup status: %s", status)
    return status


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    app.state.warmup_status = warmup_backend()
    yield
    neo4j_db.close()


app = FastAPI(
    title="BLHS Graph Chatbot Backend",
    version="2.0.0",
    description="FastAPI backend for Vietnamese criminal law scenario analysis over Neo4j.",
    lifespan=lifespan,
)

allow_origins = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(articles.router)
app.include_router(search.router)
app.include_router(chat.router)
app.include_router(agentic_rag.router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "BLHS Graph Chatbot Backend",
        "health": "/health",
        "docs": "/docs",
        "ui": "/ui",
        "neo4j_database": settings.neo4j_database,
    }


@app.get("/ui", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
