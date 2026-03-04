"""Tests for ragling.parsers.spec — SPEC.md section-level parser."""

from pathlib import Path

from ragling.parsers.spec import (
    find_nearest_spec,
    is_spec_file,
    normalize_section_type,
    parse_spec,
    split_spec_sections,
)


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


class TestParseSpec:
    """Tests for the main parse_spec function that produces Chunk objects."""

    def test_produces_one_chunk_per_section(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles authentication.\n\n## Dependencies\nUses bcrypt.\n"
        chunks = parse_spec(text, "features/auth/SPEC.md")
        assert len(chunks) == 2

    def test_chunk_text_has_context_prefix(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles authentication.\n"
        chunks = parse_spec(text, "features/auth/SPEC.md")
        assert chunks[0].text.startswith("[features/auth/SPEC.md] [spec:purpose] Auth\n")

    def test_chunk_text_includes_body(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles authentication.\n"
        chunks = parse_spec(text, "features/auth/SPEC.md")
        assert "Handles authentication." in chunks[0].text

    def test_chunk_title_is_spec_path(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles authentication.\n"
        chunks = parse_spec(text, "features/auth/SPEC.md")
        assert chunks[0].title == "features/auth/SPEC.md"

    def test_metadata_has_subsystem_name(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles authentication.\n"
        chunks = parse_spec(text, "features/auth/SPEC.md")
        assert chunks[0].metadata["subsystem_name"] == "Auth"

    def test_metadata_has_section_type(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles authentication.\n"
        chunks = parse_spec(text, "features/auth/SPEC.md")
        assert chunks[0].metadata["section_type"] == "purpose"

    def test_metadata_has_spec_path(self) -> None:
        text = "# Auth\n\n## Purpose\nHandles authentication.\n"
        chunks = parse_spec(text, "features/auth/SPEC.md")
        assert chunks[0].metadata["spec_path"] == "features/auth/SPEC.md"

    def test_metadata_has_headings(self) -> None:
        text = "# Auth\n\n## Invariants\nSome invariants.\n"
        chunks = parse_spec(text, "auth/SPEC.md")
        assert chunks[0].metadata["headings"] == ["Auth", "Invariants"]

    def test_chunk_indexes_sequential(self) -> None:
        text = "# Auth\n\n## Purpose\nA.\n\n## Testing\nB.\n\n## Dependencies\nC.\n"
        chunks = parse_spec(text, "auth/SPEC.md")
        assert [c.chunk_index for c in chunks] == [0, 1, 2]

    def test_overview_chunk_for_preamble(self) -> None:
        text = "# Auth\n\nThis is the auth subsystem.\n\n## Purpose\nHandles auth.\n"
        chunks = parse_spec(text, "auth/SPEC.md")
        assert chunks[0].metadata["section_type"] == "overview"
        assert "This is the auth subsystem." in chunks[0].text

    def test_empty_spec_produces_no_chunks(self) -> None:
        chunks = parse_spec("", "empty/SPEC.md")
        assert chunks == []

    def test_empty_body_section_still_produces_chunk(self) -> None:
        """Empty-body sections produce a prefix-only chunk for search retrieval.

        The prefix carries subsystem/section_type signal even without body text,
        so downstream search can still match on structured metadata.
        """
        text = "# Auth\n\n## Purpose\n\n## Dependencies\nUses bcrypt.\n"
        chunks = parse_spec(text, "auth/SPEC.md")
        assert len(chunks) == 2
        assert chunks[0].metadata["section_type"] == "purpose"
        assert chunks[0].text.startswith("[auth/SPEC.md] [spec:purpose] Auth\n")


class TestParseSpecOversized:
    """Tests for oversized section handling."""

    def test_large_section_splits_into_windows(self) -> None:
        long_body = " ".join(f"word{i}" for i in range(100))
        text = f"# Auth\n\n## Core Mechanism\n{long_body}\n"
        chunks = parse_spec(text, "auth/SPEC.md", chunk_size_tokens=50)
        assert len(chunks) > 1

    def test_split_chunks_keep_same_metadata(self) -> None:
        long_body = " ".join(f"word{i}" for i in range(100))
        text = f"# Auth\n\n## Core Mechanism\n{long_body}\n"
        chunks = parse_spec(text, "auth/SPEC.md", chunk_size_tokens=50)
        for chunk in chunks:
            assert chunk.metadata["section_type"] == "core_mechanism"
            assert chunk.metadata["subsystem_name"] == "Auth"

    def test_split_chunks_keep_context_prefix(self) -> None:
        long_body = " ".join(f"word{i}" for i in range(100))
        text = f"# Auth\n\n## Core Mechanism\n{long_body}\n"
        chunks = parse_spec(text, "auth/SPEC.md", chunk_size_tokens=50)
        for chunk in chunks:
            assert chunk.text.startswith("[auth/SPEC.md] [spec:core_mechanism] Auth\n")

    def test_split_chunks_have_sequential_indexes(self) -> None:
        long_body = " ".join(f"word{i}" for i in range(100))
        text = f"# Auth\n\n## Core Mechanism\n{long_body}\n"
        chunks = parse_spec(text, "auth/SPEC.md", chunk_size_tokens=50)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_split_chunks_have_independent_metadata(self) -> None:
        """Metadata dicts and headings lists must not be shared across chunks."""
        long_body = " ".join(f"word{i}" for i in range(100))
        text = f"# Auth\n\n## Core Mechanism\n{long_body}\n"
        chunks = parse_spec(text, "auth/SPEC.md", chunk_size_tokens=50)
        assert len(chunks) > 1
        # Mutate one chunk's metadata — should not affect others
        chunks[0].metadata["headings"].append("MUTATED")
        for chunk in chunks[1:]:
            assert "MUTATED" not in chunk.metadata["headings"]


class TestIsSpecFile:
    """Tests for SPEC.md filename detection."""

    def test_spec_md_exact_match(self) -> None:
        assert is_spec_file(Path("features/auth/SPEC.md")) is True

    def test_case_sensitive(self) -> None:
        assert is_spec_file(Path("spec.md")) is False

    def test_not_spec(self) -> None:
        assert is_spec_file(Path("README.md")) is False

    def test_spec_md_in_root(self) -> None:
        assert is_spec_file(Path("SPEC.md")) is True

    def test_not_spec_prefix(self) -> None:
        assert is_spec_file(Path("MY-SPEC.md")) is False


class TestFindNearestSpec:
    """Tests for .gitignore-style SPEC.md directory walking."""

    def test_finds_spec_in_same_directory(self, tmp_path: Path) -> None:
        (tmp_path / "SPEC.md").write_text("# Root\n")
        result = find_nearest_spec(tmp_path / "foo.py", tmp_path)
        assert result == "SPEC.md"

    def test_finds_spec_in_parent(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "SPEC.md").write_text("# Root\n")
        result = find_nearest_spec(sub / "foo.py", tmp_path)
        assert result == "SPEC.md"

    def test_nearest_wins(self, tmp_path: Path) -> None:
        sub = tmp_path / "features" / "auth"
        sub.mkdir(parents=True)
        (tmp_path / "SPEC.md").write_text("# Root\n")
        (sub / "SPEC.md").write_text("# Auth\n")
        result = find_nearest_spec(sub / "handlers.py", tmp_path)
        assert result == "features/auth/SPEC.md"

    def test_no_spec_returns_none(self, tmp_path: Path) -> None:
        result = find_nearest_spec(tmp_path / "foo.py", tmp_path)
        assert result is None

    def test_does_not_walk_above_root(self, tmp_path: Path) -> None:
        sub = tmp_path / "project"
        sub.mkdir()
        (tmp_path / "SPEC.md").write_text("# Root\n")
        result = find_nearest_spec(sub / "foo.py", sub)
        assert result is None
