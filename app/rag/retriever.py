"""
FAISS-based similarity retriever for policy document chunks.
Uses LangChain FAISS store + HuggingFace embeddings under the hood.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.config import settings
from app.rag.embed import embed_query
from app.rag.store import VectorStore


class PolicyRetriever:
    """
    Wraps VectorStore to provide a simple retrieve() interface.
    Lazily loads the FAISS index on first call.
    """

    def __init__(self) -> None:
        self._store: VectorStore | None = None

    def _load_store(self) -> VectorStore:
        if self._store is None:
            self._store = VectorStore()
            self._store.load()
        return self._store

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the *top_k* most semantically similar policy chunks
        for the given *query*.

        Args:
            query:  Natural-language search query.
            top_k:  Number of chunks to return. Defaults to settings.TOP_K_RESULTS.

        Returns:
            List of dicts with keys: text, source, page, score.
        """
        k = top_k or settings.TOP_K_RESULTS
        store = self._load_store()
        query_vector = embed_query(query)
        return store.search(query_vector, top_k=k)
