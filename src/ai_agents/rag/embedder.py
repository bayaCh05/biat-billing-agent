"""Local sentence-transformers embedder — singleton, no cloud calls."""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


class PCEEmbedder:
    """Singleton sentence-transformers embedder for PCE classification + duplicate detection."""

    _instance: "PCEEmbedder | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._model = None
        self._cache: dict[str, list[float]] = {}
        self._load()

    @classmethod
    def get(cls) -> "PCEEmbedder":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(_MODEL_NAME)
            logger.info("embedder_loaded model=%s", _MODEL_NAME)
        except Exception as exc:
            logger.warning("embedder_load_failed: %s — semantic features disabled", exc)
            self._model = None

    @property
    def available(self) -> bool:
        return self._model is not None

    def embed(self, text: str) -> list[float] | None:
        if not self._model:
            return None
        if text in self._cache:
            return self._cache[text]
        try:
            vec = self._model.encode(text, convert_to_numpy=True).tolist()
            self._cache[text] = vec
            return vec
        except Exception as exc:
            logger.warning("embed_failed: %s", exc)
            return None

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        if not self._model:
            return [None] * len(texts)
        try:
            vecs = self._model.encode(texts, convert_to_numpy=True).tolist()
            for t, v in zip(texts, vecs):
                self._cache[t] = v
            return vecs
        except Exception as exc:
            logger.warning("embed_batch_failed: %s", exc)
            return [None] * len(texts)
