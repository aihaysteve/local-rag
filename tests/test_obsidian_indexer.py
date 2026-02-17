"""Tests for ragling.indexers.obsidian module -- _walk_vault filtering."""

from pathlib import Path

from ragling.indexers.obsidian import _walk_vault
from ragling.indexers.project import _EXTENSION_MAP


class TestObsidianWalkVaultFiltering:
    """Tests for _walk_vault filtering files by _EXTENSION_MAP."""

    def _make_vault(self, tmp_path: Path) -> Path:
        """Create a minimal Obsidian vault directory with .obsidian marker."""
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        return vault

    def test_includes_supported_extensions(self, tmp_path: Path) -> None:
        """Files with extensions in _EXTENSION_MAP are included."""
        vault = self._make_vault(tmp_path)
        # Create files with extensions known to be in _EXTENSION_MAP
        (vault / "note.md").write_text("# Note")
        (vault / "doc.pdf").write_bytes(b"%PDF-1.4 fake")
        (vault / "image.png").write_bytes(b"\x89PNG fake")
        (vault / "data.txt").write_text("plain text")

        results = _walk_vault(vault)
        names = {p.name for p in results}

        assert "note.md" in names
        assert "doc.pdf" in names
        assert "image.png" in names
        assert "data.txt" in names

    def test_excludes_unsupported_extensions(self, tmp_path: Path) -> None:
        """Files with extensions NOT in _EXTENSION_MAP are excluded."""
        vault = self._make_vault(tmp_path)
        (vault / "unknown.xyz").write_text("mystery")
        (vault / "data.bin").write_bytes(b"\x00\x01\x02")
        (vault / "archive.tar").write_bytes(b"fake tar")
        # Also create one supported file to confirm filtering is selective
        (vault / "note.md").write_text("# Note")

        results = _walk_vault(vault)
        names = {p.name for p in results}

        assert "unknown.xyz" not in names
        assert "data.bin" not in names
        assert "archive.tar" not in names
        # Supported file is still included
        assert "note.md" in names

    def test_includes_markdown_and_pdf(self, tmp_path: Path) -> None:
        """Both .md and .pdf files in a vault are included."""
        vault = self._make_vault(tmp_path)
        (vault / "note.md").write_text("# Hello")
        (vault / "paper.pdf").write_bytes(b"%PDF-1.4 fake")

        results = _walk_vault(vault)
        names = {p.name for p in results}

        assert "note.md" in names
        assert "paper.pdf" in names

    def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        """Files inside hidden directories (like .obsidian) are excluded."""
        vault = self._make_vault(tmp_path)
        # .obsidian already exists; put a file inside it
        (vault / ".obsidian" / "config.json").write_text("{}")
        (vault / "note.md").write_text("# Note")

        results = _walk_vault(vault)
        names = {p.name for p in results}

        assert "config.json" not in names
        assert "note.md" in names

    def test_skips_hidden_files(self, tmp_path: Path) -> None:
        """Files whose names start with a dot are excluded."""
        vault = self._make_vault(tmp_path)
        (vault / ".hidden.md").write_text("# Secret")
        (vault / "visible.md").write_text("# Public")

        results = _walk_vault(vault)
        names = {p.name for p in results}

        assert ".hidden.md" not in names
        assert "visible.md" in names

    def test_skips_user_excluded_folders(self, tmp_path: Path) -> None:
        """Files inside user-excluded folders are excluded."""
        vault = self._make_vault(tmp_path)
        excluded_dir = vault / "templates"
        excluded_dir.mkdir()
        (excluded_dir / "template.md").write_text("# Template")
        (vault / "note.md").write_text("# Note")

        results = _walk_vault(vault, exclude_folders={"templates"})
        names = {p.name for p in results}

        assert "template.md" not in names
        assert "note.md" in names

    def test_includes_files_in_subdirectories(self, tmp_path: Path) -> None:
        """Files in nested subdirectories are included when supported."""
        vault = self._make_vault(tmp_path)
        sub = vault / "folder" / "subfolder"
        sub.mkdir(parents=True)
        (sub / "deep.md").write_text("# Deep")

        results = _walk_vault(vault)
        names = {p.name for p in results}

        assert "deep.md" in names

    def test_empty_vault_returns_empty_list(self, tmp_path: Path) -> None:
        """A vault with no files returns an empty list."""
        vault = self._make_vault(tmp_path)

        results = _walk_vault(vault)

        assert results == []

    def test_only_unsupported_files_returns_empty(self, tmp_path: Path) -> None:
        """A vault containing only unsupported file types returns empty."""
        vault = self._make_vault(tmp_path)
        (vault / "data.xyz").write_text("unsupported")
        (vault / "binary.bin").write_bytes(b"\x00")

        results = _walk_vault(vault)

        assert results == []

    def test_all_extension_map_keys_are_recognized(self, tmp_path: Path) -> None:
        """Every extension in _EXTENSION_MAP is accepted by _walk_vault."""
        vault = self._make_vault(tmp_path)

        # Create a file for each extension in the map
        for i, ext in enumerate(sorted(_EXTENSION_MAP.keys())):
            filename = f"file_{i}{ext}"
            (vault / filename).write_text(f"content for {ext}")

        results = _walk_vault(vault)
        result_suffixes = {p.suffix.lower() for p in results}

        for ext in _EXTENSION_MAP:
            assert ext in result_suffixes, f"Extension {ext} should be included but was not"
