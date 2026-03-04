"""SPEC.md section-level parser for Codified Context Infrastructure.

Parses SPEC.md files into section-level chunks with rich metadata:
subsystem_name, section_type, spec_path. Designed for the Codified Context
three-tier knowledge architecture.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

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


def normalize_section_type(heading: str) -> str:
    """Normalize an H2 heading to a known section type.

    Args:
        heading: The H2 heading text (without the ## prefix).

    Returns:
        A normalized section type string, or "other" for unknown headings.
    """
    key = heading.strip().lower()
    return _SECTION_MAP.get(key, "other")


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
