"""Embeddings locales y multilingües (no necesitan clave ni coste por uso).

El modelo se descarga la primera vez (~470 MB) y queda en la caché de Hugging Face.
"""
from __future__ import annotations

import os
from functools import lru_cache

import numpy as np

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer  # import perezoso: tarda en cargar
    try:
        # Si ya está descargado, no consulta Hugging Face (ahorra ~1 minuto por paso)
        return SentenceTransformer(MODEL_NAME, local_files_only=True)
    except OSError:
        return SentenceTransformer(MODEL_NAME)


def embed(texts: list[str]) -> np.ndarray:
    """Vectores normalizados: el producto escalar es directamente la similitud coseno."""
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    return _model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
