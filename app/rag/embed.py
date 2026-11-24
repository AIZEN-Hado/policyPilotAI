"""
Embedding generation using LangChain + HuggingFace SentenceTransformers.

Runs entirely on CPU — uses ZERO VRAM, leaving all 4 GB free for Ollama.
Model is downloaded once (~90 MB) and cached in ~/.cache/huggingface/.
"""
from __future__ import annotations

from typing import List

from app.config import settings

_embedder = None   # lazy-loaded on first call


def _get_embedder():
    global _embedder
    if _embedder is None:
        from langchain_huggingface import HuggingFaceEmbeddings
        _embedder = HuggingFaceEmbeddings(
            model_name=settings.EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},        # CPU only — preserve VRAM for Ollama
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embedder


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for a list of text strings.
    Runs on CPU — all VRAM stays available for the Ollama LLM.
    """
    if not texts:
        return []
    return _get_embedder().embed_documents(texts)


def embed_query(query: str) -> List[float]:
    """Embed a single query string."""
    return _get_embedder().embed_query(query)
