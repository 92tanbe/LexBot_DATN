from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


def _env_bool(*names: str, default: bool = False) -> bool:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _env_int(*names: str, default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value:
            try:
                return int(value)
            except ValueError:
                return default
    return default


def _env_float(*names: str, default: float) -> float:
    for name in names:
        value = os.getenv(name)
        if value:
            try:
                return float(value)
            except ValueError:
                return default
    return default


class Settings(BaseSettings):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password123456"
    neo4j_database: str = "neo4j"
    neo4j_connection_timeout: float = 10.0
    neo4j_query_timeout: float = 15.0

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    use_llm_fact_extractor: bool = False
    use_llm_input_understanding: bool = False
    use_llm_ner: bool = False
    use_provisional_neo4j_analysis: bool = False
    use_vector_search: bool = False
    use_reranker: bool = False
    use_hyde: bool = False

    embedding_model: str = "bkai-foundation-models/vietnamese-bi-encoder"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32
    embedding_dim: int = 768
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    rrf_k: int = 60
    cors_allow_origins: str = "*"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password123456"),
        neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
        neo4j_connection_timeout=_env_float("NEO4J_CONNECTION_TIMEOUT", default=10.0),
        neo4j_query_timeout=_env_float("NEO4J_QUERY_TIMEOUT", default=15.0),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        use_llm_fact_extractor=_env_bool("USE_LLM_FACT_EXTRACTOR", "ENABLE_LLM_FACT_EXTRACTOR"),
        use_llm_input_understanding=_env_bool("USE_LLM_INPUT_UNDERSTANDING", "ENABLE_LLM_INPUT_UNDERSTANDING"),
        use_llm_ner=_env_bool("USE_LLM_NER", "ENABLE_LLM_NER"),
        use_provisional_neo4j_analysis=_env_bool("USE_PROVISIONAL_NEO4J_ANALYSIS", "ENABLE_PROVISIONAL_NEO4J_ANALYSIS"),
        use_vector_search=_env_bool("USE_VECTOR_SEARCH", "ENABLE_VECTOR_SEARCH"),
        use_reranker=_env_bool("USE_RERANKER", "ENABLE_RERANKER"),
        use_hyde=_env_bool("USE_HYDE", "ENABLE_HYDE"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "bkai-foundation-models/vietnamese-bi-encoder"),
        embedding_device=os.getenv("EMBEDDING_DEVICE", "cpu"),
        embedding_batch_size=_env_int("EMBEDDING_BATCH_SIZE", default=32),
        embedding_dim=_env_int("EMBEDDING_DIM", default=768),
        reranker_model=os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        cors_allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*"),
    )


settings = get_settings()
