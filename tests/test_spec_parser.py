"""Tests for ragling.parsers.spec — SPEC.md section-level parser."""

from ragling.parsers.spec import normalize_section_type


class TestNormalizeSectionType:
    """Tests for heading → section_type normalization."""

    def test_purpose(self) -> None:
        assert normalize_section_type("Purpose") == "purpose"

    def test_core_mechanism(self) -> None:
        assert normalize_section_type("Core Mechanism") == "core_mechanism"

    def test_public_interface(self) -> None:
        assert normalize_section_type("Public Interface") == "public_interface"

    def test_invariants(self) -> None:
        assert normalize_section_type("Invariants") == "invariants"

    def test_failure_modes(self) -> None:
        assert normalize_section_type("Failure Modes") == "failure_modes"

    def test_testing(self) -> None:
        assert normalize_section_type("Testing") == "testing"

    def test_dependencies(self) -> None:
        assert normalize_section_type("Dependencies") == "dependencies"

    def test_unknown_heading(self) -> None:
        assert normalize_section_type("Custom Section") == "other"

    def test_case_insensitive(self) -> None:
        assert normalize_section_type("INVARIANTS") == "invariants"

    def test_extra_whitespace(self) -> None:
        assert normalize_section_type("  Core Mechanism  ") == "core_mechanism"
