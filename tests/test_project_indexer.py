"""Tests for ragling.indexers.project module -- format routing."""

import inspect
from pathlib import Path
from unittest.mock import patch

from ragling.chunker import Chunk
from ragling.config import Config
from ragling.indexers.project import _EXTENSION_MAP


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
