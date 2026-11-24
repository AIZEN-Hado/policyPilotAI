"""
Tests for the RAG pipeline.
Embeddings and FAISS are mocked — no model download needed in CI.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.utils.text_utils import chunk_text, clean_text
from app.rag.store import VectorStore


def test_clean_text_collapses_whitespace():
    assert clean_text("hello   world") == "hello world"


def test_clean_text_strips_control_chars():
    assert "\x00" not in clean_text("foo\x00bar")


def test_chunk_text_basic():
    text = "A" * 1000
    chunks = chunk_text(text, chunk_size=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_chunk_text_empty():
    assert chunk_text("") == []


def test_chunk_text_short():
    assert chunk_text("short text") == ["short text"]


@patch("app.rag.store.VectorStore._embedder")
def test_vector_store_add_and_search(mock_embedder_method):
    import numpy as np
    from langchain.schema import Document

    dim = 384
    mock_embedder = MagicMock()
    mock_embedder.embed_documents.return_value = [list(np.random.rand(dim)) for _ in range(3)]
    mock_embedder.embed_query.return_value = list(np.random.rand(dim))
    mock_embedder_method.return_value = mock_embedder

    mock_faiss = MagicMock()
    mock_faiss.similarity_search_by_vector.return_value = [
        Document(page_content=f"chunk {i}", metadata={"source": "policy.pdf", "page": 1})
        for i in range(2)
    ]

    with patch("app.rag.store.FAISS") as MockFAISS:
        MockFAISS.from_documents.return_value = mock_faiss
        store = VectorStore(index_path="/tmp/test_faiss_ollama")
        store.add_documents([{"text": f"chunk {i}", "source": "policy.pdf", "page": 1} for i in range(3)])
        results = store.search(list(np.random.rand(dim)), top_k=2)

    assert len(results) == 2
    assert "text" in results[0]
