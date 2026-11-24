"""
Text cleaning and chunking helpers.
"""
import re
from typing import List


def clean_text(text: str) -> str:
    """Normalise whitespace and remove common PDF artefacts."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> List[str]:
    """
    Split *text* into overlapping chunks of approximately *chunk_size* chars.
    """
    text = clean_text(text)
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(text):
        chunk = text[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks
