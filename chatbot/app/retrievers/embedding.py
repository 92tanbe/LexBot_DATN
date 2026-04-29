"""Wrapper BKAI bi-encoder tieng Viet.

Tai model 1 lan (singleton), ho tro batch + cache LRU cho query.
"""
from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import Iterable

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()


def _load_model():
    """Lazy load sentence-transformer."""
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer

        logger.info(
            "Load embedding model %s tren device=%s",
            settings.embedding_model,
            settings.embedding_device,
        )
        _model = SentenceTransformer(settings.embedding_model, device=settings.embedding_device)
        actual_dim = _model_dim(_model)
        if actual_dim != settings.embedding_dim:
            logger.warning(
                "Dimension thuc te %d khac config %d, dung %d",
                actual_dim,
                settings.embedding_dim,
                actual_dim,
            )
    return _model


def _model_dim(model) -> int:
    """Lay dim model, ho tro ca API moi va cu cua sentence-transformers."""
    if hasattr(model, "get_embedding_dimension"):
        try:
            return model.get_embedding_dimension()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(model, "get_sentence_embedding_dimension"):
        return model.get_sentence_embedding_dimension()
    raise RuntimeError("Khong xac dinh duoc dim cua embedding model")


def get_embedding_model():
    """Public accessor."""
    return _load_model()


def get_embedding_dim() -> int:
    """Tra ve dim that su cua model dang load."""
    return _model_dim(get_embedding_model())


def embed_texts(
    texts: list[str],
    batch_size: int | None = None,
    normalize: bool = True,
    show_progress: bool = False,
) -> np.ndarray:
    """Embed batch text. Tra ve numpy float32 [N, dim]."""
    if not texts:
        return np.zeros((0, get_embedding_dim()), dtype=np.float32)
    model = _load_model()
    bs = batch_size or settings.embedding_batch_size
    embs = model.encode(
        texts,
        batch_size=bs,
        convert_to_numpy=True,
        normalize_embeddings=normalize,
        show_progress_bar=show_progress,
    )
    return embs.astype(np.float32)


@lru_cache(maxsize=512)
def _embed_query_cached(text: str, normalize: bool) -> tuple[float, ...]:
    """Cache embed cho query."""
    vec = embed_texts([text], normalize=normalize)[0]
    return tuple(float(x) for x in vec.tolist())


def embed_query(text: str, normalize: bool = True) -> list[float]:
    """Embed mot query, co cache. Tra ve list[float] de dua thang vao Cypher."""
    text = (text or "").strip()
    if not text:
        return [0.0] * get_embedding_dim()
    return list(_embed_query_cached(text, normalize))


def chunked(iterable: Iterable, size: int):
    """Helper chia batch generator."""
    batch: list = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
