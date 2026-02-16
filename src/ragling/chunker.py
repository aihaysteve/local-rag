"""Text chunking strategies for different content types."""

import logging
import re
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


def chunk_email(subject: str, body: str, chunk_size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Chunk an email body, using subject as title context.

    Short emails become a single chunk. Longer ones are split by paragraphs
    or by word windows if paragraphs are too large.

    Args:
        subject: The email subject line.
        body: The email body text.
        chunk_size: Target chunk size in words.
        overlap: Overlap between chunks in words.

    Returns:
        List of Chunk objects.
    """
    if not body or not body.strip():
        return [
            Chunk(
                text=f"Subject: {subject}" if subject else "",
                title=subject or "(no subject)",
                chunk_index=0,
            )
        ]

    full_text = body.strip()
    title = subject or "(no subject)"

    # If short enough, return as single chunk
    if _word_count(full_text) <= chunk_size:
        return [Chunk(text=full_text, title=title, chunk_index=0)]

    # Split by double newlines (paragraphs)
    paragraphs = re.split(r"\n\s*\n", full_text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[Chunk] = []
    chunk_idx = 0
    current_text = ""

    for para in paragraphs:
        if _word_count(current_text + " " + para) <= chunk_size:
            current_text = (current_text + "\n\n" + para).strip()
        else:
            if current_text:
                chunks.append(Chunk(text=current_text, title=title, chunk_index=chunk_idx))
                chunk_idx += 1

            if _word_count(para) > chunk_size:
                # Split oversized paragraph into windows
                windows = _split_into_windows(para, chunk_size, overlap)
                for window in windows:
                    chunks.append(Chunk(text=window, title=title, chunk_index=chunk_idx))
                    chunk_idx += 1
                current_text = ""
            else:
                current_text = para

    if current_text:
        chunks.append(Chunk(text=current_text, title=title, chunk_index=chunk_idx))

    return chunks
