"""Tests for ragling.indexers.project module -- format routing."""

import inspect
from pathlib import Path
from unittest.mock import patch

from ragling.chunker import Chunk
from ragling.config import Config
from ragling.indexers.project import _EXTENSION_MAP


class TestSupportedExtensions:
    def test_code_extensions_are_supported(self) -> None:
        from ragling.indexers.project import is_supported_extension

        assert is_supported_extension(".py") is True
        assert is_supported_extension(".js") is True
        assert is_supported_extension(".go") is True
        assert is_supported_extension(".rs") is True

    def test_document_extensions_are_supported(self) -> None:
        from ragling.indexers.project import is_supported_extension

        assert is_supported_extension(".pdf") is True
        assert is_supported_extension(".md") is True
        assert is_supported_extension(".txt") is True

    def test_unknown_extensions_are_not_supported(self) -> None:
        from ragling.indexers.project import is_supported_extension

        assert is_supported_extension(".xyz") is False
        assert is_supported_extension(".zzz") is False

    def test_supported_extensions_is_frozenset(self) -> None:
        from ragling.indexers.project import _SUPPORTED_EXTENSIONS

        assert isinstance(_SUPPORTED_EXTENSIONS, frozenset)


class TestExtensionMap:
    def test_pdf_maps_to_pdf(self) -> None:
        assert _EXTENSION_MAP[".pdf"] == "pdf"

    def test_docx_maps_to_docx(self) -> None:
        assert _EXTENSION_MAP[".docx"] == "docx"

    def test_pptx_maps_to_pptx(self) -> None:
        assert _EXTENSION_MAP[".pptx"] == "pptx"

    def test_xlsx_maps_to_xlsx(self) -> None:
        assert _EXTENSION_MAP[".xlsx"] == "xlsx"

    def test_tex_maps_to_latex(self) -> None:
        assert _EXTENSION_MAP[".tex"] == "latex"

    def test_latex_maps_to_latex(self) -> None:
        assert _EXTENSION_MAP[".latex"] == "latex"

    def test_png_maps_to_image(self) -> None:
        assert _EXTENSION_MAP[".png"] == "image"

    def test_jpg_maps_to_image(self) -> None:
        assert _EXTENSION_MAP[".jpg"] == "image"

    def test_jpeg_maps_to_image(self) -> None:
        assert _EXTENSION_MAP[".jpeg"] == "image"

    def test_tiff_maps_to_image(self) -> None:
        assert _EXTENSION_MAP[".tiff"] == "image"

    def test_md_maps_to_markdown(self) -> None:
        assert _EXTENSION_MAP[".md"] == "markdown"

    def test_adoc_maps_to_asciidoc(self) -> None:
        assert _EXTENSION_MAP[".adoc"] == "asciidoc"

    def test_epub_maps_to_epub(self) -> None:
        assert _EXTENSION_MAP[".epub"] == "epub"

    def test_csv_maps_to_csv(self) -> None:
        assert _EXTENSION_MAP[".csv"] == "csv"

    def test_html_maps_to_html(self) -> None:
        assert _EXTENSION_MAP[".html"] == "html"

    def test_htm_maps_to_html(self) -> None:
        assert _EXTENSION_MAP[".htm"] == "html"

    def test_txt_maps_to_plaintext(self) -> None:
        assert _EXTENSION_MAP[".txt"] == "plaintext"

    def test_json_maps_to_plaintext(self) -> None:
        assert _EXTENSION_MAP[".json"] == "plaintext"

    def test_yaml_maps_to_plaintext(self) -> None:
        assert _EXTENSION_MAP[".yaml"] == "plaintext"

    def test_yml_maps_to_plaintext(self) -> None:
        assert _EXTENSION_MAP[".yml"] == "plaintext"


class TestDoclingRouting:
    def test_docling_formats_imported(self) -> None:
        """DOCLING_FORMATS is accessible from project module."""
        from ragling.docling_convert import DOCLING_FORMATS

        assert "pdf" in DOCLING_FORMATS
        assert "markdown" not in DOCLING_FORMATS

    def test_all_docling_extensions_have_mapping(self) -> None:
        """Every format in DOCLING_FORMATS has at least one extension mapping to it."""
        from ragling.docling_convert import DOCLING_FORMATS

        mapped_formats = set(_EXTENSION_MAP.values())
        for fmt in DOCLING_FORMATS:
            assert fmt in mapped_formats, f"DOCLING_FORMATS has '{fmt}' but no extension maps to it"

    def test_parse_and_chunk_accepts_doc_store(self) -> None:
        """_parse_and_chunk accepts optional doc_store parameter."""
        from ragling.indexers.project import _parse_and_chunk

        sig = inspect.signature(_parse_and_chunk)
        assert "doc_store" in sig.parameters

    def test_project_indexer_accepts_doc_store(self) -> None:
        """ProjectIndexer accepts optional doc_store parameter."""
        from ragling.indexers.project import ProjectIndexer

        sig = inspect.signature(ProjectIndexer.__init__)
        assert "doc_store" in sig.parameters


class TestObsidianDoclingRouting:
    def test_obsidian_index_file_accepts_doc_store(self) -> None:
        """_index_file in obsidian indexer accepts doc_store parameter."""
        from ragling.indexers.obsidian import _index_file

        sig = inspect.signature(_index_file)
        assert "doc_store" in sig.parameters

    def test_obsidian_indexer_constructor_accepts_doc_store(self) -> None:
        """ObsidianIndexer.__init__() accepts doc_store parameter."""
        from ragling.indexers.obsidian import ObsidianIndexer

        sig = inspect.signature(ObsidianIndexer.__init__)
        assert "doc_store" in sig.parameters

    def test_obsidian_indexer_index_does_not_accept_doc_store(self) -> None:
        """ObsidianIndexer.index() should NOT have doc_store parameter (use constructor)."""
        from ragling.indexers.obsidian import ObsidianIndexer

        sig = inspect.signature(ObsidianIndexer.index)
        assert "doc_store" not in sig.parameters

    def test_obsidian_indexer_stores_doc_store(self) -> None:
        """ObsidianIndexer stores doc_store as instance attribute."""
        from unittest.mock import MagicMock

        from ragling.indexers.obsidian import ObsidianIndexer

        mock_store = MagicMock()
        indexer = ObsidianIndexer([Path("/tmp/vault")], doc_store=mock_store)
        assert indexer.doc_store is mock_store

    def test_obsidian_indexer_doc_store_defaults_none(self) -> None:
        """ObsidianIndexer doc_store defaults to None."""
        from ragling.indexers.obsidian import ObsidianIndexer

        indexer = ObsidianIndexer([Path("/tmp/vault")])
        assert indexer.doc_store is None


class TestParseAndChunkDoclingRouting:
    """Tests for _parse_and_chunk Docling format routing."""

    def test_docling_format_with_doc_store_calls_convert_and_chunk(self, tmp_path: Path) -> None:
        """Docling format + doc_store should call convert_and_chunk."""
        from unittest.mock import MagicMock

        from ragling.indexers.project import _parse_and_chunk

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")
        config = Config(chunk_size_tokens=256)
        mock_store = MagicMock()

        with patch("ragling.indexers.project.convert_and_chunk") as mock_convert:
            mock_convert.return_value = [Chunk(text="text", title="test.pdf", chunk_index=0)]
            result = _parse_and_chunk(pdf_file, "pdf", config, doc_store=mock_store)

        mock_convert.assert_called_once_with(pdf_file, mock_store, chunk_max_tokens=256)
        assert len(result) == 1

    def test_docling_format_without_doc_store_returns_empty(self, tmp_path: Path) -> None:
        """Docling format without doc_store should return empty list and log ERROR."""
        from ragling.indexers.project import _parse_and_chunk

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")
        config = Config(chunk_size_tokens=256)

        result = _parse_and_chunk(pdf_file, "pdf", config, doc_store=None)
        assert result == []


class TestParseAndChunkUnifiedChunking:
    """Tests that _parse_and_chunk uses HybridChunker for all formats."""

    def test_markdown_uses_hybrid_chunker(self, tmp_path: Path) -> None:
        from ragling.indexers.project import _parse_and_chunk

        md_file = tmp_path / "note.md"
        md_file.write_text("# Heading\n\nBody text here.")
        config = Config(chunk_size_tokens=256)

        with patch("ragling.indexers.project.chunk_with_hybrid") as mock_hybrid:
            mock_hybrid.return_value = [
                Chunk(text="contextualized", title="note.md", chunk_index=0)
            ]
            chunks = _parse_and_chunk(md_file, "markdown", config)

        mock_hybrid.assert_called_once()
        assert len(chunks) == 1

    def test_markdown_preserves_obsidian_metadata(self, tmp_path: Path) -> None:
        from ragling.indexers.project import _parse_and_chunk

        md_file = tmp_path / "note.md"
        md_file.write_text("---\ntags: [python]\n---\n# Heading\n\nBody with [[Link]].")
        config = Config(chunk_size_tokens=256)

        with patch("ragling.indexers.project.chunk_with_hybrid") as mock_hybrid:
            mock_hybrid.return_value = [Chunk(text="text", title="note.md", chunk_index=0)]
            _parse_and_chunk(md_file, "markdown", config)

        # Verify extra_metadata was passed with tags and links
        call_kwargs = mock_hybrid.call_args.kwargs
        extra = call_kwargs.get("extra_metadata", {})
        assert "tags" in extra
        assert "python" in extra["tags"]

    def test_epub_uses_hybrid_chunker(self, tmp_path: Path) -> None:
        from ragling.indexers.project import _parse_and_chunk

        epub_file = tmp_path / "book.epub"
        epub_file.write_bytes(b"fake epub")
        config = Config(chunk_size_tokens=256)

        with patch("ragling.indexers.project.parse_epub") as mock_parse:
            mock_parse.return_value = [(1, "Chapter text.")]
            with patch("ragling.indexers.project.chunk_with_hybrid") as mock_hybrid:
                mock_hybrid.return_value = [Chunk(text="text", title="book.epub", chunk_index=0)]
                chunks = _parse_and_chunk(epub_file, "epub", config)

        mock_hybrid.assert_called_once()
        assert len(chunks) == 1

    def test_plaintext_uses_hybrid_chunker(self, tmp_path: Path) -> None:
        from ragling.indexers.project import _parse_and_chunk

        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Plain text content.")
        config = Config(chunk_size_tokens=256)

        with patch("ragling.indexers.project.chunk_with_hybrid") as mock_hybrid:
            mock_hybrid.return_value = [Chunk(text="text", title="notes.txt", chunk_index=0)]
            chunks = _parse_and_chunk(txt_file, "plaintext", config)

        mock_hybrid.assert_called_once()
        assert len(chunks) == 1


class TestProjectIndexerPruning:
    def test_prune_called_after_indexing(self, tmp_path: Path) -> None:
        """ProjectIndexer.index() calls prune_stale_sources after processing files."""
        from ragling.config import Config
        from ragling.db import get_connection, init_db
        from ragling.indexers.project import ProjectIndexer

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )
        conn = get_connection(config)
        init_db(conn, config)

        indexer = ProjectIndexer("test-coll", [tmp_path])

        with patch("ragling.indexers.project.prune_stale_sources", return_value=2) as mock_prune:
            result = indexer.index(conn, config)

        mock_prune.assert_called_once()
        assert result.pruned == 2
        conn.close()


class TestObsidianIndexerPruning:
    def test_prune_called_after_indexing(self, tmp_path: Path) -> None:
        """ObsidianIndexer.index() calls prune_stale_sources after processing files."""
        from ragling.config import Config
        from ragling.db import get_connection, init_db
        from ragling.indexers.obsidian import ObsidianIndexer

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )
        conn = get_connection(config)
        init_db(conn, config)

        indexer = ObsidianIndexer([vault])

        with patch("ragling.indexers.obsidian.prune_stale_sources", return_value=1) as mock_prune:
            result = indexer.index(conn, config)

        mock_prune.assert_called_once()
        assert result.pruned == 1
        conn.close()


class TestCalibreIndexerPruning:
    def test_prune_called_after_indexing(self, tmp_path: Path) -> None:
        """CalibreIndexer.index() calls prune_stale_sources after processing books."""
        from ragling.config import Config
        from ragling.db import get_connection, init_db
        from ragling.indexers.calibre_indexer import CalibreIndexer

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )
        conn = get_connection(config)
        init_db(conn, config)

        # Empty library path - no books to index, but prune should still run
        lib = tmp_path / "CalibreLibrary"
        lib.mkdir()
        indexer = CalibreIndexer([lib])

        with (
            patch("ragling.indexers.calibre_indexer.parse_calibre_library", return_value=[]),
            patch(
                "ragling.indexers.calibre_indexer.prune_stale_sources", return_value=3
            ) as mock_prune,
        ):
            result = indexer.index(conn, config)

        mock_prune.assert_called_once()
        assert result.pruned == 3
        conn.close()


class TestProjectIndexerDiscovery:
    def _setup_db(self, tmp_path: Path) -> tuple:
        from ragling.config import Config
        from ragling.db import get_connection, init_db

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )
        conn = get_connection(config)
        init_db(conn, config)
        return conn, config

    def test_obsidian_vault_delegates_to_obsidian_indexer(self, tmp_path: Path) -> None:
        """When a vault is discovered, ObsidianIndexer is called for that subdirectory."""
        conn, config = self._setup_db(tmp_path)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        vault = project_dir / "my-vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "note.md").write_text("# Hello")

        from ragling.indexers.base import IndexResult
        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("test-project", [project_dir])

        mock_result = IndexResult(indexed=1, skipped=0, errors=0, total_found=1)
        with patch("ragling.indexers.obsidian.ObsidianIndexer") as MockObsidian:
            MockObsidian.return_value.index.return_value = mock_result
            result = indexer.index(conn, config)

        MockObsidian.assert_called_once()
        assert result.indexed >= 1
        conn.close()

    def test_git_repo_delegates_to_git_indexer(self, tmp_path: Path) -> None:
        """When a git repo is discovered, GitRepoIndexer is called for that subdirectory."""
        conn, config = self._setup_db(tmp_path)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        repo = project_dir / "my-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "main.py").write_text("print('hello')")

        from ragling.indexers.base import IndexResult
        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("test-project", [project_dir])

        mock_result = IndexResult(indexed=1, skipped=0, errors=0, total_found=1)
        with patch("ragling.indexers.git_indexer.GitRepoIndexer") as MockGit:
            MockGit.return_value.index.return_value = mock_result
            result = indexer.index(conn, config)

        MockGit.assert_called_once()
        assert result.indexed >= 1
        conn.close()

    def test_no_markers_uses_flat_indexing(self, tmp_path: Path) -> None:
        """When no markers are found, falls back to existing flat behavior."""
        conn, config = self._setup_db(tmp_path)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "readme.txt").write_text("hello")

        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("test-project", [project_dir])

        with (
            patch("ragling.indexers.obsidian.ObsidianIndexer") as MockObsidian,
            patch("ragling.indexers.git_indexer.GitRepoIndexer") as MockGit,
            patch("ragling.indexers.project._parse_and_chunk", return_value=[]),
        ):
            indexer.index(conn, config)

        MockObsidian.assert_not_called()
        MockGit.assert_not_called()
        conn.close()


class TestTwoPassGitIndexing:
    def _setup_db(self, tmp_path: Path) -> tuple:
        from ragling.config import Config
        from ragling.db import get_connection, init_db

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )
        conn = get_connection(config)
        init_db(conn, config)
        return conn, config

    def test_docx_in_git_repo_gets_indexed(self, tmp_path: Path) -> None:
        """Non-code document files in a git repo are indexed via the document pass."""
        conn, config = self._setup_db(tmp_path)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        repo = project_dir / "my-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "main.py").write_text("print('hello')")
        (repo / "docs").mkdir()
        (repo / "docs" / "spec.md").write_text("# Specification\n\nDetails here.")

        from ragling.indexers.base import IndexResult
        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("test-project", [project_dir])

        git_result = IndexResult(indexed=1)
        with (
            patch("ragling.indexers.git_indexer.GitRepoIndexer") as MockGitClass,
            patch("ragling.indexers.project._parse_and_chunk") as mock_parse,
            patch("ragling.indexers.project.get_embeddings") as mock_embed,
        ):
            MockGitClass.return_value.index.return_value = git_result
            mock_parse.return_value = [
                Chunk(text="Specification details", title="spec.md", chunk_index=0)
            ]
            mock_embed.return_value = [[0.1, 0.2, 0.3, 0.4]]

            result = indexer.index(conn, config)

        # The document pass should have attempted to index spec.md
        assert mock_parse.called
        # Should have at least the git result + document result
        assert result.indexed >= 1
        conn.close()

    def test_code_files_not_double_indexed_in_doc_pass(self, tmp_path: Path) -> None:
        """Code files (.py, .js, etc.) are NOT included in the document pass."""
        conn, config = self._setup_db(tmp_path)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        repo = project_dir / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "main.py").write_text("print('hello')")
        # Only code files, no documents

        from ragling.indexers.base import IndexResult
        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("test-project", [project_dir])

        git_result = IndexResult(indexed=1)
        with (
            patch("ragling.indexers.git_indexer.GitRepoIndexer") as MockGitClass,
            patch("ragling.indexers.project._parse_and_chunk") as mock_parse,
        ):
            MockGitClass.return_value.index.return_value = git_result
            indexer.index(conn, config)

        # _parse_and_chunk should not be called for .py files (they're code)
        mock_parse.assert_not_called()
        conn.close()


class TestBackwardCompatibility:
    def _setup_db(self, tmp_path: Path) -> tuple:
        from ragling.config import Config
        from ragling.db import get_connection, init_db

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )
        conn = get_connection(config)
        init_db(conn, config)
        return conn, config

    def test_flat_project_unchanged_when_no_markers(self, tmp_path: Path) -> None:
        """ProjectIndexer with no markers behaves exactly as before discovery."""
        conn, config = self._setup_db(tmp_path)

        project_dir = tmp_path / "docs"
        project_dir.mkdir()
        (project_dir / "readme.txt").write_text("Hello world")
        (project_dir / "notes.md").write_text("# Notes")

        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("flat-project", [project_dir])

        with (
            patch("ragling.indexers.project._parse_and_chunk") as mock_parse,
            patch("ragling.indexers.project.get_embeddings") as mock_embed,
        ):
            mock_parse.return_value = [Chunk(text="text", title="test", chunk_index=0)]
            mock_embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
            result = indexer.index(conn, config)

        # Should have found and attempted to index 2 files
        assert result.total_found == 2

        # Collection should be "flat-project" with type "project"
        row = conn.execute(
            "SELECT collection_type FROM collections WHERE name = ?",
            ("flat-project",),
        ).fetchone()
        assert row["collection_type"] == "project"

        # No sub-collections should exist
        sub = conn.execute(
            "SELECT name FROM collections WHERE name LIKE 'flat-project/%'"
        ).fetchall()
        assert len(sub) == 0
        conn.close()

    def test_single_file_path_still_works(self, tmp_path: Path) -> None:
        """Passing a single file (not directory) still works."""
        conn, config = self._setup_db(tmp_path)

        single_file = tmp_path / "report.txt"
        single_file.write_text("Report content")

        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("single", [single_file])

        with (
            patch("ragling.indexers.project._parse_and_chunk") as mock_parse,
            patch("ragling.indexers.project.get_embeddings") as mock_embed,
        ):
            mock_parse.return_value = [Chunk(text="text", title="report", chunk_index=0)]
            mock_embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
            result = indexer.index(conn, config)

        assert result.total_found == 1
        conn.close()


# ---------------------------------------------------------------------------
# P2 #4 (S6.1-2): End-to-end ProjectIndexer two-pass no duplicates
# ---------------------------------------------------------------------------


class TestTwoPassNoDuplicates:
    """Verify discovery-aware indexing doesn't index any file twice."""

    def _setup_db(self, tmp_path: Path) -> tuple:
        from ragling.config import Config
        from ragling.db import get_connection, init_db

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )
        conn = get_connection(config)
        init_db(conn, config)
        return conn, config

    def test_vault_files_not_duplicated_in_leftovers(self, tmp_path: Path) -> None:
        """Files inside an Obsidian vault go to ObsidianIndexer only, not leftover indexing.

        Creates a project directory with:
        - my-vault/ (.obsidian marker, contains note.md)
        - standalone.pdf (outside the vault)

        Asserts that note.md is handled by ObsidianIndexer and standalone.pdf
        is handled by leftover indexing, with no file appearing in both paths.
        """
        conn, config = self._setup_db(tmp_path)

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Vault with a markdown file
        vault = project_dir / "my-vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        vault_note = vault / "note.md"
        vault_note.write_text("# Vault Note")

        # Standalone file outside vault
        standalone = project_dir / "standalone.pdf"
        standalone.write_bytes(b"%PDF-1.4 fake")

        from ragling.indexers.base import IndexResult
        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("test-project", [project_dir])

        # Track which paths ObsidianIndexer receives
        obsidian_paths_received: list[Path] = []

        mock_obsidian_result = IndexResult(indexed=1, skipped=0, errors=0, total_found=1)

        # Track which files go through leftover _parse_and_chunk
        leftover_files_parsed: list[Path] = []

        def tracking_parse_and_chunk(path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            leftover_files_parsed.append(path)
            return [Chunk(text="leftover content", title=path.name, chunk_index=0)]

        with (
            patch("ragling.indexers.obsidian.ObsidianIndexer") as MockObsidianClass,
            patch(
                "ragling.indexers.project._parse_and_chunk", side_effect=tracking_parse_and_chunk
            ),
            patch("ragling.indexers.project.get_embeddings", return_value=[[0.1, 0.2, 0.3, 0.4]]),
        ):
            # Capture what ObsidianIndexer is constructed with
            def capture_obsidian_init(vault_paths, doc_store=None):  # type: ignore[no-untyped-def]
                for vp in vault_paths:
                    obsidian_paths_received.append(vp)
                mock_instance = MockObsidianClass.return_value
                return mock_instance

            MockObsidianClass.side_effect = capture_obsidian_init
            MockObsidianClass.return_value.index.return_value = mock_obsidian_result

            indexer.index(conn, config)

        # Vault directory was passed to ObsidianIndexer
        assert len(obsidian_paths_received) == 1
        assert obsidian_paths_received[0] == vault

        # Leftover indexing should handle standalone.pdf but NOT vault note
        leftover_names = {f.name for f in leftover_files_parsed}
        assert "standalone.pdf" in leftover_names, "standalone.pdf should be indexed as a leftover"
        assert "note.md" not in leftover_names, (
            "note.md is inside the vault and must not appear in leftover indexing"
        )

        # No source_path appears in both paths
        vault_file_set = {vault_note.resolve()}
        leftover_file_set = {f.resolve() for f in leftover_files_parsed}
        overlap = vault_file_set & leftover_file_set
        assert overlap == set(), f"Files indexed in both vault and leftover passes: {overlap}"

        conn.close()
