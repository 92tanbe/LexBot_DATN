from app.core.config import get_settings


def test_settings_accept_railway_reranker_and_embedding_env_names(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("ENABLE_RERANKER", "true")
    monkeypatch.setenv("EMBEDDING_DEVICE", "cpu")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "16")
    monkeypatch.setenv("EMBEDDING_DIM", "768")

    settings = get_settings()

    assert settings.use_reranker is True
    assert settings.embedding_device == "cpu"
    assert settings.embedding_batch_size == 16
    assert settings.embedding_dim == 768
    get_settings.cache_clear()
