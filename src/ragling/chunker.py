"""Text chunking strategies for different content types."""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """A chunk of text with metadata."""

    text: str
    title: str
    metadata: dict = field(default_factory=dict)
    chunk_index: int = 0


def _word_count(text: str) -> int:
    """Estimate token count using word splitting."""
    return len(text.split())


def _split_into_windows(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping word-based windows."""
    words = text.split()
    if not words:
        return []

    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))
        if end >= len(words):
            break
        start = end - overlap

    return chunks
