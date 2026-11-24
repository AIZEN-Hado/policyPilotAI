"""
PDF text extraction utilities using pdfplumber.
"""
from typing import List

import pdfplumber


def extract_text_from_pdf(pdf_path: str) -> List[str]:
    """
    Extract text from each page of a PDF file.

    Returns:
        List of strings, one entry per page.
        Pages with no extractable text return an empty string.
    """
    pages: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text.strip())
    return pages
