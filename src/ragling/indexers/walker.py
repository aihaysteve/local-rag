"""Unified DFS walker for directory traversal and file routing.

Replaces the multi-indexer discovery/walking architecture with a single
depth-first traversal that routes each file to exactly one parser.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pathspec

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


# Dot-prefixed directories (.venv, .idea, etc.) are already skipped by the walker,
# but are listed here for documentation and to match the ragignore template.
BUILTIN_EXCLUDES: frozenset[str] = frozenset(
    {
        "node_modules/",
        "__pycache__/",
        "*.pyc",
        ".DS_Store",
        "vendor/",
        ".terraform/",
        ".venv/",
        ".env/",
        "dist/",
        "build/",
        ".idea/",
        ".vscode/",
        ".mypy_cache/",
        ".pytest_cache/",
        ".tox/",
        ".egg-info/",
        "cdk.out/",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "poetry.lock",
        "uv.lock",
        "go.sum",
        ".terraform.lock.hcl",
    }
)

_BUILTIN_SPEC = pathspec.PathSpec.from_lines("gitignore", BUILTIN_EXCLUDES)


@dataclass
class ExclusionConfig:
    """Configuration for file exclusion during walk."""

    global_ragignore_path: Path | None = None
    group_ragignore_path: Path | None = None


def _load_pathspec(path: Path) -> pathspec.PathSpec | None:
    """Load a pathspec from a file, returning None if the file doesn't exist."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return pathspec.PathSpec.from_lines("gitignore", text.splitlines())
    except OSError:
        return None


ParserType = Literal["spec", "docling", "markdown", "treesitter", "plaintext", "skip"]


def route_file(path: Path) -> ParserType:
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
    parser: Literal["spec", "docling", "markdown", "treesitter", "plaintext"]
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


def assign_collection(
    route: FileRoute,
    *,
    watch_name: str,
    watch_root: Path,
) -> str:
    """Assign a collection name based on file context.

    Policy: collection follows context (vault_root > git_root > watch_root).
    If the context root IS the watch root, use watch_name directly.
    Otherwise, use watch_name/relative_path.
    """
    context_root = route.vault_root or route.git_root

    if context_root is None or context_root == watch_root:
        return watch_name

    try:
        relative = context_root.relative_to(watch_root)
        return f"{watch_name}/{relative}"
    except ValueError:
        return watch_name


def format_plan(
    result: WalkResult,
    *,
    watch_name: str,
    watch_root: Path,
) -> str:
    """Format a WalkResult as a human-readable dry-run plan."""
    total_files = len(result.routes)
    lines = [
        f"Walk complete: {total_files} files in {result.stats.directories} directories",
        "",
    ]

    for parser, count in sorted(result.stats.by_parser.items()):
        lines.append(f"  {parser:12s} {count:>5d} files")
    lines.append(f"  {'skipped':12s} {result.stats.skipped:>5d} files")
    lines.append("")

    collections: dict[str, int] = {}
    for route in result.routes:
        coll = assign_collection(route, watch_name=watch_name, watch_root=watch_root)
        collections[coll] = collections.get(coll, 0) + 1

    if collections:
        lines.append("Collections:")
        for coll, count in sorted(collections.items()):
            lines.append(f"  {coll}: {count} files")
        lines.append("")

    if result.git_roots:
        lines.append(f"Git history: {len(result.git_roots)} repo(s)")

    return "\n".join(lines)


def walk(root: Path, *, exclusion_config: ExclusionConfig | None = None) -> WalkResult:
    """Walk a directory tree and produce a routing manifest.

    Single depth-first traversal that detects .git and .obsidian markers,
    tracks context, and routes each file to exactly one parser.

    Args:
        root: Root directory to walk.
        exclusion_config: Optional exclusion configuration for ragignore files.

    Returns:
        WalkResult with routing decisions and statistics.
    """
    root = root.resolve()
    result = WalkResult()
    visited: set[Path] = set()

    # Load user-level pathspec (global or per-group ragignore)
    user_spec: pathspec.PathSpec | None = None
    if exclusion_config is not None:
        # Per-group replaces global
        if exclusion_config.group_ragignore_path is not None:
            user_spec = _load_pathspec(exclusion_config.group_ragignore_path)
        elif exclusion_config.global_ragignore_path is not None:
            user_spec = _load_pathspec(exclusion_config.global_ragignore_path)

    _walk_recursive(root, root, None, None, result, visited, user_spec, [])

    return result


def _is_excluded(
    rel_path: str,
    builtin_spec: pathspec.PathSpec,
    user_spec: pathspec.PathSpec | None,
    dir_specs: list[pathspec.PathSpec],
) -> bool:
    """Check if a path is excluded by any exclusion layer.

    Built-in excludes cannot be negated. User and directory specs support
    negation via gitignore syntax, but only within a single spec. Cross-layer
    negation (e.g. user spec excludes ``*.log``, directory ``.ragignore``
    negates ``!important.log``) does not work — each layer is evaluated
    independently and the first match wins.
    """
    if builtin_spec.match_file(rel_path):
        return True
    if user_spec is not None and user_spec.match_file(rel_path):
        return True
    for spec in dir_specs:
        if spec.match_file(rel_path):
            return True
    return False


def _walk_recursive(
    current: Path,
    root: Path,
    git_root: Path | None,
    vault_root: Path | None,
    result: WalkResult,
    visited: set[Path],
    user_spec: pathspec.PathSpec | None,
    dir_specs: list[pathspec.PathSpec],
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

    # Load per-directory ignore files; copy dir_specs so siblings don't share.
    # NOTE: patterns are matched against paths relative to the walk root, not
    # relative to the directory containing the ignore file. This means anchored
    # patterns like "/build/" in a subdirectory .gitignore won't scope correctly.
    # Simple globs (*.log, *.pyc) work fine. Fix requires pairing each spec
    # with its origin directory for relative matching.
    local_specs = list(dir_specs)
    for ignore_name in (".gitignore", ".ragignore"):
        ignore_file = current / ignore_name
        if ignore_file.is_file():
            spec = _load_pathspec(ignore_file)
            if spec is not None:
                local_specs.append(spec)

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

        # Check exclusions before routing
        rel_path = str(file_path.relative_to(root))
        if _is_excluded(rel_path, _BUILTIN_SPEC, user_spec, local_specs):
            result.stats.skipped += 1
            continue

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

        # Check exclusions for directories (append "/" for directory matching)
        rel_dir = str(dir_path.relative_to(root)) + "/"
        if _is_excluded(rel_dir, _BUILTIN_SPEC, user_spec, local_specs):
            continue

        # Don't follow symlinks outside the root
        if d.is_symlink():
            try:
                target = dir_path.resolve()
            except OSError:
                continue
            if not target.is_relative_to(root):
                continue
        _walk_recursive(
            dir_path,
            root,
            git_root,
            vault_root,
            result,
            visited,
            user_spec,
            local_specs,
        )
