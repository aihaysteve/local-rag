"""PDF text extraction using pymupdf."""

import logging
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)


def parse_pdf(path: Path) -> list[tuple[int, str]]:
    """Extract text from a PDF file page by page.

    Args:
        path: Path to the PDF file.

    Returns:
        List of (page_number, text) tuples. Page numbers are 1-based.
    """
    if not path.exists():
        logger.error("PDF file not found: %s", path)
        return []

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        logger.error("Failed to open PDF %s: %s", path, e)
        return []

    pages: list[tuple[int, str]] = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text().strip()
        if text:
            pages.append((page_num + 1, text))

    doc.close()

    if not pages:
        logger.warning("No extractable text found in PDF %s (may be OCR-only)", path)

    return pages
