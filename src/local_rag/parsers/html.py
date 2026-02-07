"""HTML to plain text extraction using BeautifulSoup."""

import logging
from pathlib import Path

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_html(path: Path) -> str:
    """Extract plain text from an HTML file.

    Args:
        path: Path to the HTML file.

    Returns:
        Extracted text content with structure preserved via newlines.
    """
    if not path.exists():
        logger.error("HTML file not found: %s", path)
        return ""

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.error("Failed to read HTML file %s: %s", path, e)
        return ""

    soup = BeautifulSoup(content, "html.parser")
    text = soup.get_text(separator="\n")

    # Clean up excessive blank lines
    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)

    return cleaned
