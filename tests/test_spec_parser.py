"""Tests for ragling.parsers.spec — SPEC.md section-level parser."""

from ragling.parsers.spec import normalize_section_type, split_spec_sections


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


class TestSplitSpecSections:
    """Tests for splitting SPEC.md content into sections."""

    def test_extracts_subsystem_name_from_h1(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles authentication.\n"
        subsystem, _sections = split_spec_sections(text)
        assert subsystem == "Auth"

    def test_splits_on_h2_headings(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles authentication.\n\n## Dependencies\nUses bcrypt.\n"
        _subsystem, sections = split_spec_sections(text)
        assert len(sections) == 2
        assert sections[0].heading == "Purpose"
        assert sections[1].heading == "Dependencies"

    def test_section_body_excludes_heading(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles authentication.\n"
        _subsystem, sections = split_spec_sections(text)
        assert sections[0].body == "Handles authentication."

    def test_preamble_becomes_overview(self) -> None:
        text = "# Auth\n\nThis is the auth subsystem.\n\n## Purpose\nHandles auth.\n"
        _subsystem, sections = split_spec_sections(text)
        assert sections[0].heading == "(overview)"
        assert sections[0].body == "This is the auth subsystem."

    def test_no_preamble_no_overview(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles auth.\n"
        _subsystem, sections = split_spec_sections(text)
        assert sections[0].heading == "Purpose"

    def test_no_h1_uses_empty_subsystem(self) -> None:
        text = "## Purpose\nHandles auth.\n"
        subsystem, _sections = split_spec_sections(text)
        assert subsystem == ""

    def test_preserves_table_in_section(self) -> None:
        text = (
            "# Auth\n\n"
            "## Invariants\n"
            "| Invariant | Why |\n"
            "|---|---|\n"
            "| Tokens expire | Prevents stale sessions |\n"
            "| Passwords hashed | Security |\n"
        )
        _subsystem, sections = split_spec_sections(text)
        assert "| Tokens expire" in sections[0].body
        assert "| Passwords hashed" in sections[0].body

    def test_section_type_normalized(self) -> None:
        text = "# Auth\n\n## Failure Modes\nTimeout errors.\n"
        _subsystem, sections = split_spec_sections(text)
        assert sections[0].section_type == "failure_modes"

    def test_empty_body_still_produces_section(self) -> None:
        text = "# Auth\n\n## Purpose\n\n## Dependencies\nUses bcrypt.\n"
        _subsystem, sections = split_spec_sections(text)
        assert len(sections) == 2
        assert sections[0].body == ""
        assert sections[0].heading == "Purpose"
