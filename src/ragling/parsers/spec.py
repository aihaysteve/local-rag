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
    from ragling.document.chunker import Chunk

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
    "decision framework": "decision_framework",
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

# Regex to match fenced code block opening/closing markers
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^(`{3,}|~{3,})\s*$")


def _strip_fenced_blocks(text: str) -> str:
    """Replace content inside fenced code blocks with spaces.

    Preserves character offsets so regex positions on the stripped text
    map correctly to the original text. Supports backtick and tilde fences.
    Unclosed fences mask everything after the opening marker.

    Args:
        text: Raw markdown text.

    Returns:
        Text with fenced block interiors replaced by spaces.
    """
    result = list(text)
    lines = text.split("\n")
    pos = 0  # character position in text
    i = 0

    while i < len(lines):
        line = lines[i]
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            fence_char = fence_match.group(1)[0]
            fence_len = len(fence_match.group(1))
            # Skip the opening fence line itself
            i += 1
            pos += len(line) + 1  # +1 for newline

            # Find the closing fence
            closed = False
            while i < len(lines):
                inner_line = lines[i]
                inner_match = _FENCE_CLOSE_RE.match(inner_line)
                if (
                    inner_match
                    and inner_match.group(1)[0] == fence_char
                    and len(inner_match.group(1)) >= fence_len
                ):
                    # Closing fence found — skip it
                    i += 1
                    pos += len(inner_line) + 1
                    closed = True
                    break
                # Blank out this line's content (preserve newlines)
                for j in range(len(inner_line)):
                    result[pos + j] = " "
                i += 1
                pos += len(inner_line) + 1

            if not closed:
                # Unclosed fence — everything after is already blanked
                pass
        else:
            i += 1
            pos += len(line) + 1

    return "".join(result)


def split_spec_sections(text: str) -> tuple[str, list[SpecSection]]:
    """Split SPEC.md content into a subsystem name and list of sections.

    Extracts the subsystem name from the first H1 heading, then splits on
    H2 headings. Text between H1 and first H2 becomes an overview section.

    Args:
        text: Raw SPEC.md content.

    Returns:
        Tuple of (subsystem_name, list of SpecSection).
    """
    # Strip fenced code blocks for heading detection only
    stripped = _strip_fenced_blocks(text)

    # Extract subsystem name from H1
    h1_match = _H1_RE.search(stripped)
    subsystem = h1_match.group(1).strip() if h1_match else ""

    # Find all H2 positions
    h2_matches = list(_H2_RE.finditer(stripped))

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


def parse_dependency_edges(text: str) -> list[str]:
    """Extract internal SPEC.md paths from a Dependencies section body.

    Parses the markdown table rows in a Dependencies section and returns
    the SPEC.md paths for internal dependencies.

    Args:
        text: Raw text of a Dependencies section (including the body
            after the ``## Dependencies`` heading).

    Returns:
        List of relative SPEC.md paths (e.g., ``src/ragling/auth/SPEC.md``).
    """
    edges: list[str] = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        # Filter empty strings from leading/trailing pipes
        parts = [p for p in parts if p]
        if len(parts) >= 3 and parts[1].startswith("internal"):
            # Extract path, stripping backticks and trailing descriptions
            raw_path = parts[2]
            # Handle backtick-wrapped paths like `src/ragling/auth/SPEC.md`
            path_match = re.search(r"`([^`]+SPEC\.md)`", raw_path)
            if path_match:
                edges.append(path_match.group(1))
            elif raw_path.strip().endswith("SPEC.md"):
                edges.append(raw_path.strip().split()[0])
    return edges


def parse_spec(text: str, relative_path: str, chunk_size_tokens: int = 1024) -> list[Chunk]:
    """Parse a SPEC.md file into section-level chunks with rich metadata.

    Each H2 section becomes one chunk with a context prefix containing
    the spec path, section type, and subsystem name.

    Args:
        text: Raw SPEC.md content.
        relative_path: Path to the SPEC.md relative to the repo root.
        chunk_size_tokens: Approximate token budget per chunk (uses word
            count as a proxy, consistent with the rest of the codebase).

    Returns:
        List of Chunk objects, one per section.
    """
    from ragling.document.chunker import Chunk, split_into_windows, word_count

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

        # Empty-body sections still produce a chunk — the prefix alone
        # carries the subsystem/section_type signal for search retrieval.
        prefixed_text = prefix + section.body

        if word_count(prefixed_text) <= chunk_size_tokens:
            chunks.append(
                Chunk(
                    text=prefixed_text,
                    title=relative_path,
                    metadata={
                        "subsystem_name": subsystem,
                        "section_type": section.section_type,
                        "spec_path": relative_path,
                        "headings": list(headings),
                    },
                    chunk_index=chunk_idx,
                )
            )
            chunk_idx += 1
        else:
            # Oversized section: split into windows, preserve metadata
            prefix_words = word_count(prefix)
            available = max(chunk_size_tokens - prefix_words, 50)
            overlap = min(available // 4, 50)
            windows = split_into_windows(section.body, available, overlap)
            for window in windows:
                chunks.append(
                    Chunk(
                        text=prefix + window,
                        title=relative_path,
                        metadata={
                            "subsystem_name": subsystem,
                            "section_type": section.section_type,
                            "spec_path": relative_path,
                            "headings": list(headings),
                        },
                        chunk_index=chunk_idx,
                    )
                )
                chunk_idx += 1

    return chunks
