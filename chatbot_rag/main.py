from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from legal_rag_service import LegalRAGService


WORKDIR = Path(__file__).resolve().parent
JSON_PATH = WORKDIR / "deepseek_part2.json"


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    top_k: int = Field(default=5, ge=1, le=10)


class QueryResponse(BaseModel):
    question: str
    hints: dict
    search_terms: list[str]
    prompt_terms: list[str]
    amount_value: float | None = None
    rows: list[dict]
    explanation: str | None = None
    final_answer: str


service: LegalRAGService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service
    service = LegalRAGService(
        json_path=JSON_PATH,
        neo4j_uri=os.getenv("NEO4J_URI", "neo4j+s://5f55db16.databases.neo4j.io"),
        neo4j_user=os.getenv("NEO4J_USER", "5f55db16"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "kmXynRPm0qTXvMd2tVBdS_jhIncfh0sReKsCOnckURg"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )
    try:
        yield
    finally:
        if service is not None:
            service.close()
            service = None


from fastapi.responses import RedirectResponse

app = FastAPI(title="Legal Neo4j RAG API", version="1.0.0", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return {}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/rag/query", response_model=QueryResponse)
def rag_query(payload: QueryRequest) -> QueryResponse:
    if service is None:
        raise HTTPException(status_code=503, detail="RAG service is not ready")
    result = service.generate(payload.question, top_k=payload.top_k)
    return QueryResponse(question=payload.question, **result)
