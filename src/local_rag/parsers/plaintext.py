"""Plain text file reader."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_plaintext(path: Path) -> str:
    """Read a plain text file and return its content.

    Args:
        path: Path to the text file.

    Returns:
        File content as a string.
    """
    if not path.exists():
        logger.error("File not found: %s", path)
        return ""

    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.error("Failed to read file %s: %s", path, e)
        return ""
