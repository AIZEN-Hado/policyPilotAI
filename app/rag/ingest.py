"""
PDF loading, chunking, and FAISS ingestion pipeline.
Uses LangChain text splitter for clean semantic chunking.

Usage (CLI):
    python -m app.rag.ingest
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.rag.store import VectorStore
from app.utils.pdf_utils import extract_text_from_pdf
from app.utils.text_utils import chunk_text

logger = logging.getLogger(__name__)


def ingest_policies(policy_dir: str | None = None) -> int:
    """
    Load all PDFs from *policy_dir*, chunk them, generate HuggingFace
    embeddings via LangChain, and upsert into the FAISS vector store.

    Returns:
        Total number of chunks indexed.
    """
    policy_dir = Path(policy_dir or settings.POLICY_PDF_DIR)
    if not policy_dir.exists():
        raise FileNotFoundError(f"Policy directory not found: {policy_dir}")

    pdf_files = list(policy_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning("No PDF files found in %s", policy_dir)
        return 0

    store = VectorStore()
    total_chunks = 0

    for pdf_path in pdf_files:
        logger.info("Ingesting: %s", pdf_path.name)
        pages = extract_text_from_pdf(str(pdf_path))

        for page_num, page_text in enumerate(pages, start=1):
            chunks = chunk_text(
                page_text,
                chunk_size=settings.CHUNK_SIZE,
                overlap=settings.CHUNK_OVERLAP,
            )
            docs = [
                {
                    "text":   chunk,
                    "source": pdf_path.name,
                    "page":   page_num,
                }
                for chunk in chunks
            ]
            store.add_documents(docs)
            total_chunks += len(docs)

    store.save()
    logger.info("Ingestion complete. Total chunks indexed: %d", total_chunks)
    return total_chunks


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = ingest_policies()
    print(f"✅ Ingested {n} chunks into the vector store.")
