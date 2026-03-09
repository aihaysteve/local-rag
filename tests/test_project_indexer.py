"""Tests for ragling.indexers.project module -- format routing."""

import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

from ragling.document.chunker import Chunk
from ragling.config import Config
from ragling.indexers.format_routing import EXTENSION_MAP, is_supported_extension


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


_EXTENSION_CASES = [
    (".pdf", "pdf"),
    (".docx", "docx"),
    (".pptx", "pptx"),
    (".xlsx", "xlsx"),
    (".tex", "latex"),
    (".latex", "latex"),
    (".png", "image"),
    (".jpg", "image"),
    (".jpeg", "image"),
    (".tiff", "image"),
    (".md", "markdown"),
    (".adoc", "asciidoc"),
    (".epub", "epub"),
    (".csv", "csv"),
    (".html", "html"),
    (".htm", "html"),
    (".txt", "plaintext"),
    (".json", "plaintext"),
    (".yaml", "plaintext"),
    (".yml", "plaintext"),
]


class TestExtensionMap:
    @pytest.mark.parametrize("ext,expected", _EXTENSION_CASES)
    def test_extension_maps_correctly(self, ext: str, expected: str) -> None:
        assert EXTENSION_MAP[ext] == expected


_AUDIO_EXTENSIONS = [
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".flac",
    ".mp4",
    ".avi",
    ".mov",
    ".opus",
    ".mkv",
    ".mka",
]


class TestAudioExtensionMap:
    """All audio/video extensions should map to 'audio' source type."""

    @pytest.mark.parametrize("ext", _AUDIO_EXTENSIONS)
    def test_audio_extension_maps_to_audio(self, ext: str) -> None:
        assert EXTENSION_MAP[ext] == "audio"

    @pytest.mark.parametrize("ext", _AUDIO_EXTENSIONS)
    def test_audio_extension_is_supported(self, ext: str) -> None:
        assert is_supported_extension(ext)


class TestDoclingRouting:
    def test_docling_formats_imported(self) -> None:
        """DOCLING_FORMATS is accessible from project module."""
        from ragling.document.docling_convert import DOCLING_FORMATS

        assert "pdf" in DOCLING_FORMATS
        assert "markdown" not in DOCLING_FORMATS

    def test_all_docling_extensions_have_mapping(self) -> None:
        """Every format in DOCLING_FORMATS has at least one extension mapping to it."""
        from ragling.document.docling_convert import DOCLING_FORMATS

        mapped_formats = set(EXTENSION_MAP.values())
        for fmt in DOCLING_FORMATS:
            assert fmt in mapped_formats, f"DOCLING_FORMATS has '{fmt}' but no extension maps to it"

    def test_parse_and_chunk_accepts_doc_store(self) -> None:
        """_parse_and_chunk accepts optional doc_store parameter."""
        from ragling.indexers.format_routing import parse_and_chunk

        sig = inspect.signature(parse_and_chunk)
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

        from ragling.indexers.format_routing import parse_and_chunk

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")
        config = Config(chunk_size_tokens=256)
        mock_store = MagicMock()

        with patch("ragling.indexers.format_routing.convert_and_chunk") as mock_convert:
            mock_convert.return_value = [Chunk(text="text", title="test.pdf", chunk_index=0)]
            result = parse_and_chunk(pdf_file, "pdf", config, doc_store=mock_store)

        mock_convert.assert_called_once_with(
            pdf_file,
            mock_store,
            chunk_max_tokens=256,
            source_type="pdf",
            asr_model="small",
            config=config,
        )
        assert len(result) == 1

    def test_docling_format_without_doc_store_returns_empty(self, tmp_path: Path) -> None:
        """Docling format without doc_store should return empty list and log ERROR."""
        from ragling.indexers.format_routing import parse_and_chunk

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")
        config = Config(chunk_size_tokens=256)

        result = parse_and_chunk(pdf_file, "pdf", config, doc_store=None)
        assert result == []


class TestParseAndChunkUnifiedChunking:
    """Tests that _parse_and_chunk uses HybridChunker for all formats."""

    def test_markdown_uses_hybrid_chunker(self, tmp_path: Path) -> None:
        from ragling.indexers.format_routing import parse_and_chunk

        md_file = tmp_path / "note.md"
        md_file.write_text("# Heading\n\nBody text here.")
        config = Config(chunk_size_tokens=256)

        with patch("ragling.indexers.format_routing.chunk_with_hybrid") as mock_hybrid:
            mock_hybrid.return_value = [
                Chunk(text="contextualized", title="note.md", chunk_index=0)
            ]
            chunks = parse_and_chunk(md_file, "markdown", config)

        mock_hybrid.assert_called_once()
        assert len(chunks) == 1

    def test_markdown_preserves_obsidian_metadata(self, tmp_path: Path) -> None:
        from ragling.indexers.format_routing import parse_and_chunk

        md_file = tmp_path / "note.md"
        md_file.write_text("---\ntags: [python]\n---\n# Heading\n\nBody with [[Link]].")
        config = Config(chunk_size_tokens=256)

        with patch("ragling.indexers.format_routing.chunk_with_hybrid") as mock_hybrid:
            mock_hybrid.return_value = [Chunk(text="text", title="note.md", chunk_index=0)]
            parse_and_chunk(md_file, "markdown", config)

        # Verify extra_metadata was passed with tags and links
        call_kwargs = mock_hybrid.call_args.kwargs
        extra = call_kwargs.get("extra_metadata", {})
        assert "tags" in extra
        assert "python" in extra["tags"]

    def test_epub_uses_hybrid_chunker(self, tmp_path: Path) -> None:
        from ragling.indexers.format_routing import parse_and_chunk

        epub_file = tmp_path / "book.epub"
        epub_file.write_bytes(b"fake epub")
        config = Config(chunk_size_tokens=256)

        with patch("ragling.indexers.format_routing.parse_epub") as mock_parse:
            mock_parse.return_value = [(1, "Chapter text.")]
            with patch("ragling.indexers.format_routing.chunk_with_hybrid") as mock_hybrid:
                mock_hybrid.return_value = [Chunk(text="text", title="book.epub", chunk_index=0)]
                chunks = parse_and_chunk(epub_file, "epub", config)

        mock_hybrid.assert_called_once()
        assert len(chunks) == 1

    def test_plaintext_uses_hybrid_chunker(self, tmp_path: Path) -> None:
        from ragling.indexers.format_routing import parse_and_chunk

        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Plain text content.")
        config = Config(chunk_size_tokens=256)

        with patch("ragling.indexers.format_routing.chunk_with_hybrid") as mock_hybrid:
            mock_hybrid.return_value = [Chunk(text="text", title="notes.txt", chunk_index=0)]
            chunks = parse_and_chunk(txt_file, "plaintext", config)

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


class TestProjectIndexerFlatIndexing:
    """ProjectIndexer now always uses flat indexing (discovery removed).

    Discovery-aware context routing is handled by the unified DFS walker.
    """

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

    def test_indexes_files_without_delegation(self, tmp_path: Path) -> None:
        """ProjectIndexer indexes all files directly, no delegation to specialized indexers."""
        conn, config = self._setup_db(tmp_path)

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "readme.txt").write_text("hello")

        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("test-project", [project_dir])

        with patch("ragling.indexers.project.parse_and_chunk", return_value=[]):
            result = indexer.index(conn, config)

        # No errors, file was found
        assert result.errors == 0
        assert result.total_found == 1
        conn.close()


class TestProjectIndexerRepoDocuments:
    """Tests for _index_repo_documents (still used by indexing queue)."""

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

    def test_indexes_non_code_files_in_repo(self, tmp_path: Path) -> None:
        """Non-code document files in a git repo are indexed via the document pass."""
        conn, config = self._setup_db(tmp_path)

        repo = tmp_path / "my-repo"
        repo.mkdir()
        (repo / "main.py").write_text("print('hello')")
        (repo / "docs").mkdir()
        (repo / "docs" / "spec.md").write_text("# Specification\n\nDetails here.")

        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("test-project", [repo])

        with (
            patch("ragling.indexers.project.parse_and_chunk") as mock_parse,
            patch("ragling.indexers.project.get_embeddings") as mock_embed,
        ):
            mock_parse.return_value = [
                Chunk(text="Specification details", title="spec.md", chunk_index=0)
            ]
            mock_embed.return_value = [[0.1, 0.2, 0.3, 0.4]]

            result = indexer._index_repo_documents(conn, config, repo, "test-project", force=False)

        assert mock_parse.called
        assert result.indexed >= 1
        conn.close()

    def test_skips_code_files_in_doc_pass(self, tmp_path: Path) -> None:
        """Code files (.py, .js, etc.) are NOT included in the document pass."""
        conn, config = self._setup_db(tmp_path)

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("print('hello')")

        from ragling.indexers.project import ProjectIndexer

        indexer = ProjectIndexer("test-project", [repo])

        with patch("ragling.indexers.project.parse_and_chunk") as mock_parse:
            indexer._index_repo_documents(conn, config, repo, "test-project", force=False)

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
            patch("ragling.indexers.project.parse_and_chunk") as mock_parse,
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
            patch("ragling.indexers.project.parse_and_chunk") as mock_parse,
            patch("ragling.indexers.project.get_embeddings") as mock_embed,
        ):
            mock_parse.return_value = [Chunk(text="text", title="report", chunk_index=0)]
            mock_embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
            result = indexer.index(conn, config)

        assert result.total_found == 1
        conn.close()



# Discovery-aware duplicate prevention tests removed — this is now handled
# by the unified DFS walker (see tests/test_walker.py integration tests).


class TestProjectIndexerStatusReporting:
    """Tests for two-pass status reporting in ProjectIndexer."""

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

    def test_flat_indexing_reports_file_level_status(self, tmp_path: Path) -> None:
        """Flat indexing calls set_file_total and file_processed on status."""
        from ragling.indexing_status import IndexingStatus
        from ragling.indexers.project import ProjectIndexer

        conn, config = self._setup_db(tmp_path)

        project_dir = tmp_path / "docs"
        project_dir.mkdir()
        (project_dir / "a.txt").write_text("File A content here")
        (project_dir / "b.txt").write_text("File B content here")

        status = IndexingStatus()
        indexer = ProjectIndexer("test-project", [project_dir])

        with (
            patch("ragling.indexers.project.parse_and_chunk") as mock_parse,
            patch("ragling.indexers.project.get_embeddings") as mock_embed,
        ):
            mock_parse.return_value = [Chunk(text="text", title="test", chunk_index=0)]
            mock_embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
            result = indexer.index(conn, config, status=status)

        # Both files should be indexed
        assert result.indexed == 2

        # Status should show all files processed
        d = status.to_dict()
        assert d is not None
        assert d["collections"]["test-project"]["processed"] == 2
        assert d["collections"]["test-project"]["remaining"] == 0

        conn.close()

    def test_status_not_set_when_none(self, tmp_path: Path) -> None:
        """ProjectIndexer works fine when status=None."""
        from ragling.indexers.project import ProjectIndexer

        conn, config = self._setup_db(tmp_path)

        project_dir = tmp_path / "docs"
        project_dir.mkdir()
        (project_dir / "a.txt").write_text("content")

        indexer = ProjectIndexer("test-project", [project_dir])

        with (
            patch("ragling.indexers.project.parse_and_chunk") as mock_parse,
            patch("ragling.indexers.project.get_embeddings") as mock_embed,
        ):
            mock_parse.return_value = [Chunk(text="text", title="test", chunk_index=0)]
            mock_embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
            # Should not raise
            result = indexer.index(conn, config, status=None)

        assert result.indexed == 1
        conn.close()


class TestSpecMdRouting:
    """Tests for SPEC.md files being routed to the spec parser."""

    def test_spec_md_uses_spec_parser(self, tmp_path: Path) -> None:  # Tests Indexers INV-10
        spec = tmp_path / "SPEC.md"
        spec.write_text("# Auth\n\n## Purpose\nHandles auth.\n\n## Dependencies\nUses bcrypt.\n")

        from ragling.config import Config
        from ragling.indexers.format_routing import parse_and_chunk

        config = Config(db_path=tmp_path / "test.db", embedding_dimensions=4)
        chunks = parse_and_chunk(spec, "spec", config)

        assert len(chunks) == 2
        assert chunks[0].metadata["subsystem_name"] == "Auth"
        assert chunks[0].metadata["section_type"] == "purpose"

    def test_spec_md_detected_as_markdown_still_routes_to_spec_parser(self, tmp_path: Path) -> None:
        """Even if source_type is 'markdown', SPEC.md should use spec parser."""
        spec = tmp_path / "SPEC.md"
        spec.write_text("# Auth\n\n## Purpose\nHandles auth.\n")

        from ragling.config import Config
        from ragling.indexers.format_routing import parse_and_chunk

        config = Config(db_path=tmp_path / "test.db", embedding_dimensions=4)
        chunks = parse_and_chunk(spec, "markdown", config)

        assert chunks[0].metadata["subsystem_name"] == "Auth"

    def test_spec_md_uses_source_path_for_context(self, tmp_path: Path) -> None:
        """source_path is used as relative_path in spec metadata, not bare filename."""
        spec = tmp_path / "SPEC.md"
        spec.write_text("# Auth\n\n## Purpose\nHandles auth.\n")

        from ragling.config import Config
        from ragling.indexers.format_routing import parse_and_chunk

        config = Config(db_path=tmp_path / "test.db", embedding_dimensions=4)
        full_path = str(spec.resolve())
        chunks = parse_and_chunk(spec, "spec", config, source_path=full_path)

        assert chunks[0].metadata["spec_path"] == full_path
        assert full_path in chunks[0].text  # context prefix uses full path

    def test_spec_md_falls_back_to_filename_without_source_path(self, tmp_path: Path) -> None:
        """Without source_path, falls back to filename for backward compat."""
        spec = tmp_path / "SPEC.md"
        spec.write_text("# Auth\n\n## Purpose\nHandles auth.\n")

        from ragling.config import Config
        from ragling.indexers.format_routing import parse_and_chunk

        config = Config(db_path=tmp_path / "test.db", embedding_dimensions=4)
        chunks = parse_and_chunk(spec, "spec", config)

        assert chunks[0].metadata["spec_path"] == "SPEC.md"

    def test_regular_md_still_uses_markdown_pipeline(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# Hello\n\nThis is a readme.\n")

        from ragling.config import Config
        from ragling.indexers.format_routing import parse_and_chunk

        config = Config(db_path=tmp_path / "test.db", embedding_dimensions=4)
        chunks = parse_and_chunk(readme, "markdown", config)

        assert "subsystem_name" not in chunks[0].metadata
