"""Directory discovery for auto-detecting Obsidian vaults and git repos.

Recursively scans a root directory for .obsidian and .git markers,
classifying each discovery for delegation to the appropriate indexer.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

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

    Args:
        root_path: The root directory to scan.

    Returns:
        DiscoveryResult with classified discoveries.
    """
    root_path = root_path.resolve()
    vaults: list[DiscoveredSource] = []
    repos: list[DiscoveredSource] = []
    claimed: set[Path] = set()

    _scan_recursive(root_path, root_path, vaults, repos, claimed)

    return DiscoveryResult(vaults=vaults, repos=repos, leftover_paths=[])


def _scan_recursive(
    current: Path,
    root: Path,
    vaults: list[DiscoveredSource],
    repos: list[DiscoveredSource],
    claimed: set[Path],
) -> None:
    """Recursively scan directories for markers.

    Args:
        current: Directory currently being scanned.
        root: The original root path (for computing relative names).
        vaults: Accumulator for discovered vaults.
        repos: Accumulator for discovered repos.
        claimed: Set of paths already claimed by a discovery.
    """
    try:
        entries = list(current.iterdir())
    except PermissionError:
        logger.warning("Permission denied, skipping: %s", current)
        return

    entry_names = {e.name for e in entries if e.is_dir()}

    has_obsidian = ".obsidian" in entry_names
    has_git = ".git" in entry_names

    if has_obsidian:
        rel = current.relative_to(root)
        name = str(rel) if rel != Path(".") else ""
        vaults.append(
            DiscoveredSource(
                path=current,
                relative_name=name or current.name,
                source_type="obsidian",
            )
        )
        claimed.add(current)
    elif has_git:
        rel = current.relative_to(root)
        name = str(rel) if rel != Path(".") else ""
        repos.append(
            DiscoveredSource(
                path=current,
                relative_name=name or current.name,
                source_type="git",
            )
        )
        claimed.add(current)

    # Continue scanning subdirectories (even inside claims, to find nested markers)
    for entry in sorted(entries):
        if entry.is_dir() and not entry.name.startswith("."):
            _scan_recursive(entry, root, vaults, repos, claimed)
