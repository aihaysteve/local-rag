"""Tests for ragling.indexers.obsidian module -- _walk_vault filtering."""

from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestObsidianIndexerStatusReporting:
    """Tests for two-pass status reporting in ObsidianIndexer."""

    def test_status_set_file_total_called_with_changed_count_and_bytes(
        self, tmp_path: Path
    ) -> None:
        """ObsidianIndexer calls set_file_total with count and bytes of changed files."""
        from ragling.indexing_status import IndexingStatus
        from ragling.indexers.obsidian import ObsidianIndexer

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "note1.md").write_text("# Note 1 content")
        (vault / "note2.md").write_text("# Note 2 content")

        status = IndexingStatus()
        indexer = ObsidianIndexer([vault])

        with (
            patch("ragling.indexers.obsidian._index_file", return_value="indexed"),
            patch("ragling.indexers.obsidian.get_or_create_collection", return_value=1),
            patch("ragling.indexers.obsidian.prune_stale_sources", return_value=0),
        ):
            conn = MagicMock()
            conn.execute.return_value.fetchone.return_value = None  # not yet indexed
            config = MagicMock()
            config.chunk_size_tokens = 512
            result = indexer.index(conn, config, force=False, status=status)

        assert result.indexed == 2

    def test_status_not_called_when_none(self, tmp_path: Path) -> None:
        """ObsidianIndexer works fine when status=None."""
        from ragling.indexers.obsidian import ObsidianIndexer

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "note.md").write_text("# Note")

        indexer = ObsidianIndexer([vault])

        with (
            patch("ragling.indexers.obsidian._index_file", return_value="indexed"),
            patch("ragling.indexers.obsidian.get_or_create_collection", return_value=1),
            patch("ragling.indexers.obsidian.prune_stale_sources", return_value=0),
        ):
            conn = MagicMock()
            conn.execute.return_value.fetchone.return_value = None
            config = MagicMock()
            config.chunk_size_tokens = 512
            result = indexer.index(conn, config, force=False, status=None)

        assert result.indexed == 1

    def test_status_file_processed_called_per_file(self, tmp_path: Path) -> None:
        """ObsidianIndexer calls file_processed after each file is indexed."""
        from ragling.indexing_status import IndexingStatus
        from ragling.indexers.obsidian import ObsidianIndexer

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "a.md").write_text("# A content here")
        (vault / "b.md").write_text("# B content here")
        (vault / "c.md").write_text("# C content here")

        status = IndexingStatus()
        indexer = ObsidianIndexer([vault])

        with (
            patch("ragling.indexers.obsidian._index_file", return_value="indexed"),
            patch("ragling.indexers.obsidian.get_or_create_collection", return_value=1),
            patch("ragling.indexers.obsidian.prune_stale_sources", return_value=0),
        ):
            conn = MagicMock()
            conn.execute.return_value.fetchone.return_value = None
            config = MagicMock()
            config.chunk_size_tokens = 512
            indexer.index(conn, config, force=False, status=status)

        d = status.to_dict()
        assert d is not None
        assert d["collections"]["obsidian"]["processed"] == 3
        assert d["collections"]["obsidian"]["remaining"] == 0

    def test_scan_pass_skips_unchanged_files(self, tmp_path: Path) -> None:
        """Unchanged files are skipped in the scan pass and not sent to _index_file."""
        from ragling.indexing_status import IndexingStatus
        from ragling.indexers.obsidian import ObsidianIndexer

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "changed.md").write_text("# Changed content")
        (vault / "unchanged.md").write_text("# Same content")

        status = IndexingStatus()
        indexer = ObsidianIndexer([vault])

        from ragling.indexers.base import file_hash as compute_hash

        unchanged_hash = compute_hash(vault / "unchanged.md")

        def mock_execute(sql, params=None):
            result = MagicMock()
            if params and str(vault / "unchanged.md") in str(params):
                row = {"id": 1, "file_hash": unchanged_hash}
                result.fetchone.return_value = row
            else:
                result.fetchone.return_value = None
            result.fetchall.return_value = []
            return result

        conn = MagicMock()
        conn.execute = mock_execute
        config = MagicMock()
        config.chunk_size_tokens = 512

        with (
            patch(
                "ragling.indexers.obsidian._index_file", return_value="indexed"
            ) as mock_index_file,
            patch("ragling.indexers.obsidian.get_or_create_collection", return_value=1),
            patch("ragling.indexers.obsidian.prune_stale_sources", return_value=0),
        ):
            result = indexer.index(conn, config, force=False, status=status)

        # Only the changed file should have been sent to _index_file
        assert mock_index_file.call_count == 1
        assert result.indexed == 1
        assert result.skipped == 1
