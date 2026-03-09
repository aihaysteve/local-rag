"""Unified DFS walker for directory traversal and file routing.

Replaces the multi-indexer discovery/walking architecture with a single
depth-first traversal that routes each file to exactly one parser.
"""

from __future__ import annotations

from pathlib import Path

from ragling.parsers.code import _CODE_EXTENSION_MAP, _CODE_FILENAME_MAP
from ragling.parsers.spec import is_spec_file

# --- Extension sets ---
# Docling-handled formats: rich documents requiring conversion pipeline.
DOCLING_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".epub": "epub",
    ".tex": "latex",
    ".latex": "latex",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".webp": "image",
    ".csv": "csv",
    ".adoc": "asciidoc",
    ".vtt": "vtt",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".aac": "audio",
    ".ogg": "audio",
    ".flac": "audio",
    ".opus": "audio",
    ".mp4": "audio",
    ".avi": "audio",
    ".mov": "audio",
    ".mkv": "audio",
    ".mka": "audio",
}

# Plaintext formats: structured/semi-structured text without a specialized parser.
PLAINTEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt",
        ".log",
        ".ini",
        ".cfg",
    }
)


def route_file(path: Path) -> str:
    """Route a file to exactly one parser based on filename and extension.

    Priority order (first match wins):
    1. SPEC.md -> "spec"
    2. Docling formats -> "docling"
    3. Markdown (.md) -> "markdown"
    4. Tree-sitter languages -> "treesitter"
    5. Plaintext extensions -> "plaintext"
    6. Everything else -> "skip"

    Args:
        path: File path (relative or absolute).

    Returns:
        Parser name string: "spec", "docling", "markdown", "treesitter",
        "plaintext", or "skip".
    """
    # 1. SPEC.md (must check before markdown)
    if is_spec_file(path):
        return "spec"

    ext = path.suffix.lower()

    # 2. Docling formats
    if ext in DOCLING_EXTENSIONS:
        return "docling"

    # 3. Markdown
    if ext == ".md":
        return "markdown"

    # 4. Tree-sitter (by extension or filename)
    if path.name in _CODE_FILENAME_MAP or ext in _CODE_EXTENSION_MAP:
        return "treesitter"

    # 5. Plaintext
    if ext in PLAINTEXT_EXTENSIONS:
        return "plaintext"

    # 6. Skip
    return "skip"
