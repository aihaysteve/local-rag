"""Unified DFS walker for directory traversal and file routing.

Replaces the multi-indexer discovery/walking architecture with a single
depth-first traversal that routes each file to exactly one parser.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
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


logger = logging.getLogger(__name__)


@dataclass
class FileRoute:
    """A file with its routing decision and walk context."""

    path: Path
    parser: str  # "spec", "docling", "markdown", "treesitter", "plaintext"
    git_root: Path | None
    vault_root: Path | None


@dataclass
class WalkStats:
    """Statistics collected during a walk."""

    by_parser: dict[str, int] = field(default_factory=dict)
    skipped: int = 0
    directories: int = 0


@dataclass
class WalkResult:
    """Complete result of walking a directory tree."""

    routes: list[FileRoute] = field(default_factory=list)
    git_roots: set[Path] = field(default_factory=set)
    stats: WalkStats = field(default_factory=WalkStats)


def walk(root: Path) -> WalkResult:
    """Walk a directory tree and produce a routing manifest.

    Single depth-first traversal that detects .git and .obsidian markers,
    tracks context, and routes each file to exactly one parser.

    Args:
        root: Root directory to walk.

    Returns:
        WalkResult with routing decisions and statistics.
    """
    root = root.resolve()
    result = WalkResult()
    visited: set[Path] = set()

    _walk_recursive(root, root, None, None, result, visited)

    return result


def _walk_recursive(
    current: Path,
    root: Path,
    git_root: Path | None,
    vault_root: Path | None,
    result: WalkResult,
    visited: set[Path],
) -> None:
    """Recursively walk a directory, tracking context."""
    try:
        real_path = current.resolve()
    except OSError:
        return

    if real_path in visited:
        return
    visited.add(real_path)

    result.stats.directories += 1

    try:
        entries = list(os.scandir(current))
    except PermissionError:
        logger.warning("Permission denied, skipping: %s", current)
        return

    # Separate files and directories, detect markers
    files: list[os.DirEntry[str]] = []
    dirs: list[os.DirEntry[str]] = []
    has_git = False
    has_obsidian = False

    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            if entry.name == ".git":
                has_git = True
            elif entry.name == ".obsidian":
                has_obsidian = True
            else:
                dirs.append(entry)
        elif entry.is_file(follow_symlinks=False):
            files.append(entry)

    # Update context based on markers
    if has_git:
        git_root = current
        result.git_roots.add(current)
    if has_obsidian:
        vault_root = current

    # Route files
    for f in sorted(files, key=lambda e: e.name):
        if f.name.startswith("."):
            continue
        file_path = Path(f.path)
        parser = route_file(file_path)
        if parser == "skip":
            result.stats.skipped += 1
            continue
        result.routes.append(
            FileRoute(
                path=file_path,
                parser=parser,
                git_root=git_root,
                vault_root=vault_root,
            )
        )
        result.stats.by_parser[parser] = result.stats.by_parser.get(parser, 0) + 1

    # Recurse into subdirectories
    for d in sorted(dirs, key=lambda e: e.name):
        if d.name.startswith("."):
            continue
        dir_path = Path(d.path)
        # Don't follow symlinks outside the root
        if d.is_symlink():
            try:
                target = dir_path.resolve()
            except OSError:
                continue
            if not target.is_relative_to(root):
                continue
        _walk_recursive(dir_path, root, git_root, vault_root, result, visited)
