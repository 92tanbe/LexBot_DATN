"""Cau hinh tap trung cho chatbot RAG BLHS.

Doc cac bien moi truong tu chatbot/.env (uu tien khi co) hoac bien he thong.
Tat ca cac module khac chi import `settings` tu day.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator


def _load_env() -> Path | None:
    """Tim va nap file .env theo thu tu uu tien.

    Thu tu kiem tra:
        1. CHATBOT_ENV_FILE  (bien moi truong)
        2. <cwd>/.env
        3. <cwd>/chatbot/.env
        4. <repo_root>/chatbot/.env  (suy ra tu vi tri file nay)
    """
    candidates: list[Path] = []
    explicit = os.getenv("CHATBOT_ENV_FILE")
    if explicit:
        candidates.append(Path(explicit))

    cwd = Path.cwd()
    candidates.append(cwd / ".env")
    candidates.append(cwd / "chatbot" / ".env")

    here = Path(__file__).resolve()
    chatbot_root = here.parents[2]
    candidates.append(chatbot_root / ".env")

    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=True)
            return path

    load_dotenv(override=True)
    return None


_ENV_PATH = _load_env()


def _getenv_required(name: str) -> str:
    """Lay bien bat buoc va bao loi ro khi deploy thieu cau hinh."""
    value = (os.getenv(name) or "").strip()
    if not value:
        raise ValueError(f"Thieu bien moi truong bat buoc: {name}")
    return value


def _optional_env(name: str) -> str | None:
    """Bien moi truong tu chon — chuoi rong -> None."""
    value = (os.getenv(name) or "").strip()
    return value if value else None


def _neo4j_allow_localhost() -> bool:
    """Cho phep bolt://localhost chi khi co co y (dev local)."""
    return os.getenv("NEO4J_ALLOW_LOCALHOST", "").strip().lower() in ("1", "true", "yes")


def _neo4j_uri_uses_loopback(uri: str) -> bool:
    """True neu host la localhost / 127.0.0.1 / ::1."""
    try:
        parsed = urlparse(uri)
        host = (parsed.hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1")
    except ValueError:
        u = uri.lower()
        return "localhost" in u or "127.0.0.1" in u


class Settings(BaseModel):
    """Bien moi truong cua dich vu."""

    # ----- Neo4j -----
    neo4j_uri: str = Field(default_factory=lambda: _getenv_required("NEO4J_URI"))
    neo4j_user: str = Field(default_factory=lambda: _getenv_required("NEO4J_USER"))
    neo4j_password: str = Field(default_factory=lambda: _getenv_required("NEO4J_PASSWORD"))
    neo4j_database: str | None = Field(default_factory=lambda: os.getenv("NEO4J_DATABASE") or None)

    @model_validator(mode="after")
    def _reject_localhost_uri_on_deploy(self):
        # Nhieu nen tang dat template NEO4J_URI=bolt://localhost — can bao loi ro.
        if _neo4j_uri_uses_loopback(self.neo4j_uri) and not _neo4j_allow_localhost():
            raise ValueError(
                "NEO4J_URI dang tro ve localhost; tren server deploy can URI Neo4j Aura/cloud. "
                "Dat NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD trong Environment Variables (Secrets) "
                "cua nen tang va xoa gia tri mac dinh localhost. "
                "Neu chay Neo4j tren may local thi them NEO4J_ALLOW_LOCALHOST=true vao .env."
            )
        return self

    # ----- OpenAI -----
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    # ----- Embedding -----
    embedding_model: str = Field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "bkai-foundation-models/vietnamese-bi-encoder")
    )
    embedding_dim: int = Field(default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "768")))
    embedding_batch_size: int = Field(default_factory=lambda: int(os.getenv("EMBEDDING_BATCH_SIZE", "32")))
    embedding_device: str = Field(default_factory=lambda: os.getenv("EMBEDDING_DEVICE", "cpu"))

    # ----- Reranker -----
    reranker_model: str = Field(
        default_factory=lambda: os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    )
    reranker_top_k: int = Field(default_factory=lambda: int(os.getenv("RERANKER_TOP_K", "8")))
    enable_reranker: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_RERANKER", "true").lower() == "true"
    )

    # ----- Vector index -----
    dieu_vector_index: str = Field(default="dieu_embedding")
    rule_vector_index: str = Field(default="rule_embedding")

    # ----- Retrieval -----
    rrf_k: int = Field(default_factory=lambda: int(os.getenv("RRF_K", "60")))
    top_k_dieu: int = Field(default_factory=lambda: int(os.getenv("TOP_K_DIEU", "10")))
    top_k_khoan: int = Field(default_factory=lambda: int(os.getenv("TOP_K_KHOAN", "20")))
    top_k_fulltext: int = Field(default_factory=lambda: int(os.getenv("TOP_K_FULLTEXT", "10")))
    candidate_top_k: int = Field(default_factory=lambda: int(os.getenv("CANDIDATE_TOP_K", "30")))
    rewritten_query_max: int = Field(default_factory=lambda: int(os.getenv("REWRITTEN_QUERY_MAX", "8")))
    llm_rewrite_query_max: int = Field(default_factory=lambda: int(os.getenv("LLM_REWRITE_QUERY_MAX", "4")))
    enable_llm_hyde: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_LLM_HYDE", "true").lower() == "true"
    )

    # ----- PDF tra cứu văn bản (VB hợp nhất BLHS, mode tra_cuu_pdf) -----
    blhs_pdf_path: str | None = Field(default_factory=lambda: _optional_env("BLHS_PDF_PATH"))

    # ----- App -----
    app_host: str = Field(default_factory=lambda: os.getenv("CHATBOT_HOST", "0.0.0.0"))
    app_port: int = Field(default_factory=lambda: int(os.getenv("CHATBOT_PORT", "8001")))
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            o.strip()
            for o in os.getenv(
                "CHATBOT_CORS_ORIGINS",
                "http://localhost:5173,http://localhost:8000,http://localhost:8501",
            ).split(",")
            if o.strip()
        ]
    )
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # ----- Misc -----
    env_file_path: str | None = Field(default=str(_ENV_PATH) if _ENV_PATH else None)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Tra ve singleton Settings (cache 1 lan)."""
    return Settings()


settings = get_settings()
