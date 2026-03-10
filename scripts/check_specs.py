#!/usr/bin/env python3
"""Validate SPEC.md files for structural quality.

Checks:
- INV/FAIL IDs are sequential within each file (1, 2, 3, ...)
- SPEC.md files don't exceed the 150-line threshold
- All directories with Python source have a SPEC.md in their tree
- Markdown links in documentation files resolve to existing targets

Usage:
    python scripts/check_specs.py [--fix-numbering]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SPEC_LINE_LIMIT = 150
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src" / "ragling"
DOCS_ROOT = PROJECT_ROOT / "docs"

# Directories that are subsystems (have Python source files)
SUBSYSTEM_DIRS = [
    d for d in SRC_ROOT.iterdir()
    if d.is_dir() and not d.name.startswith("__") and any(d.glob("*.py"))
]


def check_id_numbering(spec_path: Path) -> list[str]:
    """Check that INV-N and FAIL-N IDs are sequential within a file."""
    errors = []
    text = spec_path.read_text()

    for prefix in ("INV", "FAIL"):
        pattern = rf"\|\s*{prefix}-(\d+)\s*\|"
        ids = [int(m.group(1)) for m in re.finditer(pattern, text)]
        if not ids:
            continue

        expected = list(range(1, len(ids) + 1))
        if ids != expected:
            rel = spec_path.relative_to(PROJECT_ROOT)
            errors.append(
                f"{rel}: {prefix} IDs are {ids}, expected {expected}"
            )

    return errors


def check_spec_length(spec_path: Path) -> list[str]:
    """Check that SPEC.md files don't exceed the line limit."""
    lines = len(spec_path.read_text().splitlines())
    if lines > SPEC_LINE_LIMIT:
        rel = spec_path.relative_to(PROJECT_ROOT)
        return [f"{rel}: {lines} lines (limit: {SPEC_LINE_LIMIT})"]
    return []


def check_spec_coverage() -> list[str]:
    """Check that every subsystem directory has a SPEC.md in its tree."""
    errors = []
    for d in SUBSYSTEM_DIRS:
        # Walk up from the directory to find the nearest SPEC.md
        current = d
        found = False
        while current >= SRC_ROOT:
            if (current / "SPEC.md").exists():
                found = True
                break
            current = current.parent
        if not found:
            rel = d.relative_to(PROJECT_ROOT)
            errors.append(f"{rel}: no SPEC.md found in directory tree up to src/ragling/")
    return errors


def check_markdown_links(md_path: Path) -> list[str]:
    """Check that relative markdown links resolve to existing files."""
    errors = []
    text = md_path.read_text()
    rel_path = md_path.relative_to(PROJECT_ROOT)

    # Match [text](link) but skip external URLs and anchors-only
    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    for match in link_pattern.finditer(text):
        link = match.group(2)

        # Skip external URLs, mailto, and anchor-only links
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue

        # Split off anchor
        file_part = link.split("#")[0]
        if not file_part:
            continue

        # Resolve relative to the markdown file's directory
        target = (md_path.parent / file_part).resolve()
        if not target.exists():
            errors.append(f"{rel_path}: broken link [{match.group(1)}]({link}) -> {file_part}")

    return errors


def check_anchor_references(md_path: Path) -> list[str]:
    """Check that anchor references point to existing headings."""
    errors = []
    text = md_path.read_text()
    rel_path = md_path.relative_to(PROJECT_ROOT)

    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+#[^)]+)\)")
    for match in link_pattern.finditer(text):
        link = match.group(2)
        if link.startswith(("http://", "https://")):
            continue

        parts = link.split("#", 1)
        if len(parts) != 2:
            continue

        file_part, anchor = parts
        if file_part:
            target_path = (md_path.parent / file_part).resolve()
        else:
            target_path = md_path

        if not target_path.exists():
            continue  # Already caught by check_markdown_links

        target_text = target_path.read_text()
        # Build anchor from headings (GitHub-flavored markdown rules)
        headings = re.findall(r"^#{1,6}\s+(.+)$", target_text, re.MULTILINE)
        anchors = set()
        for h in headings:
            # GFM anchor generation: lowercase, replace spaces with -, remove non-word chars except -
            slug = h.lower().strip()
            slug = re.sub(r"[^\w\s-]", "", slug)
            slug = re.sub(r"\s+", "-", slug)
            anchors.add(slug)

        if anchor not in anchors:
            errors.append(
                f"{rel_path}: broken anchor [{match.group(1)}]({link}) "
                f"-> #{anchor} not found in {target_path.name}"
            )

    return errors


def main() -> int:
    all_errors: list[str] = []

    # Find all SPEC.md files
    spec_files = list(PROJECT_ROOT.glob("**/SPEC.md"))
    # Exclude worktrees
    spec_files = [f for f in spec_files if ".worktrees" not in str(f.relative_to(PROJECT_ROOT))]

    for spec in spec_files:
        all_errors.extend(check_id_numbering(spec))
        all_errors.extend(check_spec_length(spec))

    # Check subsystem coverage
    all_errors.extend(check_spec_coverage())

    # Check markdown links in all doc files
    md_files = (
        list(DOCS_ROOT.glob("*.md"))
        + list(DOCS_ROOT.glob("**/*.md"))
        + [PROJECT_ROOT / "README.md"]
        + [PROJECT_ROOT / "CLAUDE.md"]
        + [PROJECT_ROOT / "CONTRIBUTING.md"]
    )
    md_files = list(set(f for f in md_files if ".worktrees" not in str(f.relative_to(PROJECT_ROOT))))

    for md in md_files:
        if md.exists():
            all_errors.extend(check_markdown_links(md))
            all_errors.extend(check_anchor_references(md))

    if all_errors:
        print("SPEC.md validation errors:")
        for err in sorted(all_errors):
            print(f"  - {err}")
        return 1

    print(f"All checks passed ({len(spec_files)} SPEC.md files, {len(md_files)} doc files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
