"""
FAISS vector store via LangChain.
Uses HuggingFace SentenceTransformers for embeddings (CPU only).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from app.config import settings


class VectorStore:
    """
    Thin wrapper around LangChain's FAISS vector store.
    Embeddings run on CPU — no VRAM consumed here.
    """

    def __init__(self, index_path: str | None = None) -> None:
        self.index_path = Path(index_path or settings.FAISS_INDEX_PATH)
        self._store = None

    def _embedder(self):
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name=settings.EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

    def add_documents(self, docs: List[Dict[str, Any]]) -> None:
        from langchain.schema import Document
        from langchain_community.vectorstores import FAISS

        lc_docs = [
            Document(
                page_content=d["text"],
                metadata={"source": d.get("source", ""), "page": d.get("page", 0)},
            )
            for d in docs
        ]
        embedder = self._embedder()
        if self._store is None:
            self._store = FAISS.from_documents(lc_docs, embedder)
        else:
            self._store.add_documents(lc_docs)

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        if self._store is None:
            return []
        results = self._store.similarity_search_by_vector(query_vector, k=top_k)
        return [
            {
                "text":   doc.page_content,
                "source": doc.metadata.get("source", ""),
                "page":   doc.metadata.get("page", 0),
                "score":  0.0,
            }
            for doc in results
        ]

    def save(self) -> None:
        if self._store is None:
            return
        self.index_path.mkdir(parents=True, exist_ok=True)
        self._store.save_local(str(self.index_path))

    def load(self) -> None:
        from langchain_community.vectorstores import FAISS
        if not self.index_path.exists():
            raise FileNotFoundError(
                f"FAISS index not found at {self.index_path}. "
                "Run ingestion first: POST /api/v1/ingest"
            )
        self._store = FAISS.load_local(
            str(self.index_path),
            self._embedder(),
            allow_dangerous_deserialization=True,
        )
