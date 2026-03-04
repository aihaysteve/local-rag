"""SPEC.md section-level parser for Codified Context Infrastructure.

Parses SPEC.md files into section-level chunks with rich metadata:
subsystem_name, section_type, spec_path. Designed for the Codified Context
three-tier knowledge architecture.
"""

from __future__ import annotations

import logging

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
