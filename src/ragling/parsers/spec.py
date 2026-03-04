"""SPEC.md section-level parser for Codified Context Infrastructure.

Parses SPEC.md files into section-level chunks with rich metadata:
subsystem_name, section_type, spec_path. Designed for the Codified Context
three-tier knowledge architecture.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ragling.chunker import Chunk

logger = logging.getLogger(__name__)

# Known section types from the SPEC.md schema
_SECTION_MAP: dict[str, str] = {
    "purpose": "purpose",
    "core mechanism": "core_mechanism",
    "public interface": "public_interface",
    "invariants": "invariants",
    "failure modes": "failure_modes",
    "testing": "testing",
    "dependencies": "dependencies",
}


def find_nearest_spec(file_path: Path, repo_root: Path) -> str | None:
    """Walk up from a file to find the nearest SPEC.md, stopping at repo root.

    Mirrors .gitignore resolution — the nearest SPEC.md wins.

    Args:
        file_path: Path to the file being indexed.
        repo_root: Root of the repository (stop boundary).

    Returns:
        Relative path to the SPEC.md from repo_root, or None if not found.
    """
    current = file_path.parent if file_path.is_file() or not file_path.exists() else file_path
    repo_root = repo_root.resolve()
    current = current.resolve()

    while True:
        spec_candidate = current / "SPEC.md"
        if spec_candidate.exists():
            return str(spec_candidate.relative_to(repo_root))

        if current == repo_root:
            break

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def normalize_section_type(heading: str) -> str:
    """Normalize an H2 heading to a known section type.

    Args:
        heading: The H2 heading text (without the ## prefix).

    Returns:
        A normalized section type string, or "other" for unknown headings.
    """
    key = heading.strip().lower()
    return _SECTION_MAP.get(key, "other")


def is_spec_file(path: Path) -> bool:
    """Check if a file path is a SPEC.md file.

    Args:
        path: File path to check.

    Returns:
        True if the filename is exactly 'SPEC.md'.
    """
    return path.name == "SPEC.md"


@dataclass
class SpecSection:
    """A single section from a SPEC.md file."""

    heading: str
    body: str
    section_type: str


# Regex to match H1 and H2 headings
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def split_spec_sections(text: str) -> tuple[str, list[SpecSection]]:
    """Split SPEC.md content into a subsystem name and list of sections.

    Extracts the subsystem name from the first H1 heading, then splits on
    H2 headings. Text between H1 and first H2 becomes an overview section.

    Args:
        text: Raw SPEC.md content.

    Returns:
        Tuple of (subsystem_name, list of SpecSection).
    """
    # Extract subsystem name from H1
    h1_match = _H1_RE.search(text)
    subsystem = h1_match.group(1).strip() if h1_match else ""

    # Find all H2 positions
    h2_matches = list(_H2_RE.finditer(text))

    sections: list[SpecSection] = []

    # Handle preamble (text between H1 and first H2)
    if h1_match:
        preamble_start = h1_match.end()
        preamble_end = h2_matches[0].start() if h2_matches else len(text)
        preamble = text[preamble_start:preamble_end].strip()
        if preamble:
            sections.append(
                SpecSection(
                    heading="(overview)",
                    body=preamble,
                    section_type="overview",
                )
            )

    # Split on H2 headings
    for i, match in enumerate(h2_matches):
        heading = match.group(1).strip()
        body_start = match.end()
        body_end = h2_matches[i + 1].start() if i + 1 < len(h2_matches) else len(text)
        body = text[body_start:body_end].strip()

        sections.append(
            SpecSection(
                heading=heading,
                body=body,
                section_type=normalize_section_type(heading),
            )
        )

    return subsystem, sections


def parse_spec(text: str, relative_path: str, chunk_size_tokens: int = 1024) -> list[Chunk]:
    """Parse a SPEC.md file into section-level chunks with rich metadata.

    Each H2 section becomes one chunk with a context prefix containing
    the spec path, section type, and subsystem name.

    Args:
        text: Raw SPEC.md content.
        relative_path: Path to the SPEC.md relative to the repo root.
        chunk_size_tokens: Maximum words per chunk before splitting.

    Returns:
        List of Chunk objects, one per section.
    """
    from ragling.chunker import Chunk, _split_into_windows, _word_count

    if not text.strip():
        return []

    subsystem, sections = split_spec_sections(text)
    if not sections:
        return []

    chunks: list[Chunk] = []
    chunk_idx = 0

    for section in sections:
        prefix = f"[{relative_path}] [spec:{section.section_type}] {subsystem}\n"

        headings: list[str] = []
        if subsystem:
            headings.append(subsystem)
        if section.heading != "(overview)":
            headings.append(section.heading)

        def _make_metadata() -> dict[str, object]:
            """Build a fresh metadata dict with independent mutable values."""
            return {
                "subsystem_name": subsystem,
                "section_type": section.section_type,
                "spec_path": relative_path,
                "headings": list(headings),
            }

        prefixed_text = prefix + section.body

        if _word_count(prefixed_text) <= chunk_size_tokens:
            chunks.append(
                Chunk(
                    text=prefixed_text,
                    title=relative_path,
                    metadata=_make_metadata(),
                    chunk_index=chunk_idx,
                )
            )
            chunk_idx += 1
        else:
            # Oversized section: split into windows, preserve metadata
            prefix_words = _word_count(prefix)
            available = max(chunk_size_tokens - prefix_words, 50)
            overlap = min(available // 4, 50)
            windows = _split_into_windows(section.body, available, overlap)
            for window in windows:
                chunks.append(
                    Chunk(
                        text=prefix + window,
                        title=relative_path,
                        metadata=_make_metadata(),
                        chunk_index=chunk_idx,
                    )
                )
                chunk_idx += 1

    return chunks
