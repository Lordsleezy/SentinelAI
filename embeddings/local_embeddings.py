"""
Deterministic local embeddings for offline memory retrieval.

This is intentionally dependency-light. It gives SentinelAI semantic-ish
retrieval even before Qdrant/Chroma embedding backends are configured.

Optional upgrade: if sentence-transformers is installed, get_best_embedding_provider()
returns a SentenceTransformerEmbeddingProvider with genuine semantic vectors.
"""

import hashlib
import logging
import math
import re
from typing import List

logger = logging.getLogger(__name__)


class LocalEmbeddingProvider:
    """Hashing-vector embedding provider."""

    def __init__(self, dimensions: int = 256):
        self.dimensions = dimensions

    def embed(self, text: str) -> List[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-zA-Z0-9_./:-]+", (text or "").lower())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[idx] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    @staticmethod
    def cosine(left: List[float], right: List[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        return sum(a * b for a, b in zip(left, right))


class SentenceTransformerEmbeddingProvider:
    """
    Semantic embeddings via sentence-transformers (optional upgrade).

    Uses all-MiniLM-L6-v2 (~80 MB, downloaded on first use).
    Model is cached at class level so the expensive load only happens once.
    Falls back silently to LocalEmbeddingProvider if the package is absent.
    """

    _model = None  # class-level cache

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name

    def _get_model(self):
        if SentenceTransformerEmbeddingProvider._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            SentenceTransformerEmbeddingProvider._model = SentenceTransformer(self.model_name)
        return SentenceTransformerEmbeddingProvider._model

    def embed(self, text: str) -> List[float]:
        model = self._get_model()
        vec = model.encode(text or "", convert_to_numpy=True)
        return vec.tolist()

    @staticmethod
    def cosine(left: List[float], right: List[float]) -> float:
        return LocalEmbeddingProvider.cosine(left, right)


def get_best_embedding_provider() -> LocalEmbeddingProvider:
    """
    Return the best available embedding provider.

    Tries sentence-transformers first (genuine semantic vectors).
    Falls back to the deterministic hash-based provider if the package
    is not installed — no error, no noise.
    """
    try:
        provider = SentenceTransformerEmbeddingProvider()
        provider.embed("warmup")  # trigger import + model load once
        logger.debug("Using SentenceTransformerEmbeddingProvider for RAG")
        return provider
    except Exception:
        logger.debug("sentence-transformers unavailable; using LocalEmbeddingProvider")
        return LocalEmbeddingProvider()
