"""Directory discovery for auto-detecting Obsidian vaults and git repos.

Recursively scans a root directory for .obsidian and .git markers,
classifying each discovery for delegation to the appropriate indexer.
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ragling.db import delete_collection

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredSource:
    """A directory identified by a marker (.obsidian or .git)."""

    path: Path
    relative_name: str
    source_type: str  # "obsidian" or "git"


@dataclass
class DiscoveryResult:
    """Result of scanning a directory tree for markers."""

    vaults: list[DiscoveredSource] = field(default_factory=list)
    repos: list[DiscoveredSource] = field(default_factory=list)
    leftover_paths: list[Path] = field(default_factory=list)


def discover_sources(root_path: Path) -> DiscoveryResult:
    """Scan a directory tree for .obsidian and .git markers.

    Walks root_path recursively. Directories containing .obsidian are classified
    as vaults; directories containing .git (but not .obsidian) are classified as
    repos. .obsidian takes precedence when both exist.

    Files not inside any discovered subtree are returned as leftovers.

    Args:
        root_path: The root directory to scan.

    Returns:
        DiscoveryResult with classified discoveries and leftover files.
    """
    root_path = root_path.resolve()
    vaults: list[DiscoveredSource] = []
    repos: list[DiscoveredSource] = []
    claimed: set[Path] = set()
    visited: set[Path] = set()

    _scan_recursive(root_path, root_path, vaults, repos, claimed, visited)

    leftover_paths = _collect_leftovers(root_path, claimed)

    return DiscoveryResult(vaults=vaults, repos=repos, leftover_paths=leftover_paths)


def _is_under_claimed(path: Path, claimed: set[Path]) -> bool:
    """Check if a path is inside any claimed directory.

    Args:
        path: File path to check.
        claimed: Set of claimed directory paths.

    Returns:
        True if path is inside (or equal to) any claimed directory.
    """
    resolved = path.resolve()
    return any(resolved.is_relative_to(c) for c in claimed)


def _collect_leftovers(root: Path, claimed: set[Path]) -> list[Path]:
    """Walk root and collect files not inside any claimed subtree.

    Args:
        root: Root directory to walk.
        claimed: Set of claimed directory paths.

    Returns:
        Sorted list of leftover file paths.
    """
    leftovers: list[Path] = []
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        if item.name.startswith("."):
            continue
        rel = item.relative_to(root)
        if any(part.startswith(".") for part in rel.parts[:-1]):
            continue
        if not _is_under_claimed(item, claimed):
            leftovers.append(item)
    return leftovers


def _scan_recursive(
    current: Path,
    root: Path,
    vaults: list[DiscoveredSource],
    repos: list[DiscoveredSource],
    claimed: set[Path],
    visited: set[Path],
) -> None:
    """Recursively scan directories for markers.

    Tracks resolved real paths in ``visited`` to detect symlink cycles
    and avoid infinite recursion.

    Args:
        current: Directory currently being scanned.
        root: The original root path (for computing relative names).
        vaults: Accumulator for discovered vaults.
        repos: Accumulator for discovered repos.
        claimed: Set of paths already claimed by a discovery.
        visited: Set of resolved real paths already visited (cycle detection).
    """
    real_path = current.resolve()
    if real_path in visited:
        return
    visited.add(real_path)

    try:
        entries = list(current.iterdir())
    except PermissionError:
        logger.warning("Permission denied, skipping: %s", current)
        return

    entry_names = {e.name for e in entries if e.is_dir()}

    has_obsidian = ".obsidian" in entry_names
    has_git = ".git" in entry_names

    if has_obsidian or has_git:
        rel = current.relative_to(root)
        relative_name = str(rel) if str(rel) != "." else ""
        source = DiscoveredSource(
            path=current,
            relative_name=relative_name,
            source_type="obsidian" if has_obsidian else "git",
        )
        if has_obsidian:
            vaults.append(source)
        else:
            repos.append(source)
        claimed.add(current)

    # Continue scanning subdirectories (even inside claims, to find nested markers)
    for entry in sorted(entries):
        if entry.is_dir() and not entry.name.startswith("."):
            _scan_recursive(entry, root, vaults, repos, claimed, visited)


def reconcile_sub_collections(
    conn: sqlite3.Connection,
    project_name: str,
    discovery: DiscoveryResult,
) -> list[str]:
    """Delete sub-collections whose markers no longer exist.

    Compares existing sub-collections (matching '{project_name}/%') against
    current discovery results. Any sub-collection not in the current discovery
    is deleted.

    Args:
        conn: SQLite database connection.
        project_name: The parent project name.
        discovery: Current discovery results to compare against.

    Returns:
        List of deleted sub-collection names.
    """
    # Build set of expected sub-collection names from discovery
    expected: set[str] = set()
    for vault in discovery.vaults:
        if vault.relative_name:
            expected.add(f"{project_name}/{vault.relative_name}")
    for repo in discovery.repos:
        if repo.relative_name:
            expected.add(f"{project_name}/{repo.relative_name}")

    # Find existing sub-collections in DB
    rows = conn.execute(
        "SELECT name FROM collections WHERE name LIKE ?",
        (f"{project_name}/%",),
    ).fetchall()

    deleted: list[str] = []
    for row in rows:
        name = row["name"]
        if name not in expected:
            delete_collection(conn, name)
            deleted.append(name)

    return deleted
