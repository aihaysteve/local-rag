"""Tests for ragling.docling_convert module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ragling.chunker import Chunk
from ragling.doc_store import DocStore


@pytest.fixture()
def store(tmp_path: Path) -> DocStore:
    return DocStore(tmp_path / "doc_store.sqlite")


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    f = tmp_path / "test.pdf"
    f.write_bytes(b"%PDF-1.4 fake content")
    return f


class TestConvertAndChunk:
    def test_returns_list_of_chunks(self, store: DocStore, sample_file: Path) -> None:
        """convert_and_chunk returns a list of Chunk dataclass instances."""
        from ragling.docling_convert import convert_and_chunk

        with patch("ragling.docling_convert._convert_with_docling") as mock_convert:
            # Mock returns a dict (what DocStore caches)
            mock_convert.return_value = {"name": "mock", "schema_name": "DoclingDocument"}

            with patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls:
                mock_doc = MagicMock()
                mock_doc_cls.model_validate.return_value = mock_doc

                with patch("ragling.docling_convert._get_tokenizer") as mock_get_tok:
                    mock_get_tok.return_value = MagicMock()

                    with patch("ragling.docling_convert.HybridChunker") as mock_chunker_cls:
                        mock_chunk = MagicMock()
                        mock_chunk.meta.headings = ["Section 1"]
                        mock_chunker = MagicMock()
                        mock_chunker.chunk.return_value = [mock_chunk]
                        mock_chunker.contextualize.return_value = "Section 1\nchunk text"
                        mock_chunker_cls.return_value = mock_chunker

                        chunks = convert_and_chunk(sample_file, store)

        assert len(chunks) == 1
        assert isinstance(chunks[0], Chunk)
        assert chunks[0].text == "Section 1\nchunk text"
        assert chunks[0].title == "test.pdf"
        assert chunks[0].chunk_index == 0

    def test_chunk_metadata_includes_source_path(self, store: DocStore, sample_file: Path) -> None:
        from ragling.docling_convert import convert_and_chunk

        with patch("ragling.docling_convert._convert_with_docling") as mock_convert:
            mock_convert.return_value = {"name": "mock"}

            with patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls:
                mock_doc = MagicMock()
                mock_doc_cls.model_validate.return_value = mock_doc

                with patch("ragling.docling_convert._get_tokenizer") as mock_get_tok:
                    mock_get_tok.return_value = MagicMock()

                    with patch("ragling.docling_convert.HybridChunker") as mock_chunker_cls:
                        mock_chunk = MagicMock()
                        mock_chunk.meta.headings = ["H1"]
                        mock_chunker = MagicMock()
                        mock_chunker.chunk.return_value = [mock_chunk]
                        mock_chunker.contextualize.return_value = "H1\ntext"
                        mock_chunker_cls.return_value = mock_chunker

                        chunks = convert_and_chunk(sample_file, store)

        assert chunks[0].metadata["source_path"] == str(sample_file)
        assert chunks[0].metadata["headings"] == ["H1"]

    def test_multiple_chunks_have_sequential_indices(
        self, store: DocStore, sample_file: Path
    ) -> None:
        from ragling.docling_convert import convert_and_chunk

        with patch("ragling.docling_convert._convert_with_docling") as mock_convert:
            mock_convert.return_value = {"name": "mock"}

            with patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls:
                mock_doc = MagicMock()
                mock_doc_cls.model_validate.return_value = mock_doc

                with patch("ragling.docling_convert._get_tokenizer") as mock_get_tok:
                    mock_get_tok.return_value = MagicMock()

                    with patch("ragling.docling_convert.HybridChunker") as mock_chunker_cls:
                        chunks_data = []
                        for i in range(3):
                            mc = MagicMock()
                            mc.meta.headings = [f"Section {i}"]
                            chunks_data.append(mc)
                        mock_chunker = MagicMock()
                        mock_chunker.chunk.return_value = chunks_data
                        mock_chunker.contextualize.side_effect = [
                            f"Section {i}\ntext {i}" for i in range(3)
                        ]
                        mock_chunker_cls.return_value = mock_chunker

                        chunks = convert_and_chunk(sample_file, store)

        assert len(chunks) == 3
        assert [c.chunk_index for c in chunks] == [0, 1, 2]


class TestGetConverter:
    """Tests for the enriched converter configuration."""

    def test_get_converter_returns_document_converter(self) -> None:
        from ragling.docling_convert import get_converter

        get_converter.cache_clear()
        with patch("ragling.docling_convert.DocumentConverter") as mock_cls:
            mock_cls.return_value = MagicMock()
            converter = get_converter()
            assert converter is mock_cls.return_value

    def test_get_converter_configures_pdf_enrichments(self) -> None:
        from ragling.docling_convert import get_converter

        get_converter.cache_clear()
        with patch("ragling.docling_convert.DocumentConverter") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_converter()

            # Verify format_options was passed
            call_kwargs = mock_cls.call_args
            assert call_kwargs is not None
            # The key check: format_options was passed (not bare DocumentConverter())
            assert "format_options" in (call_kwargs.kwargs or {})

    def test_get_converter_enables_picture_description(self) -> None:
        from ragling.docling_convert import get_converter

        get_converter.cache_clear()
        with patch("ragling.docling_convert.DocumentConverter") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_converter()
            call_kwargs = mock_cls.call_args.kwargs
            format_options = call_kwargs["format_options"]
            # PDF format option should have pipeline_options with enrichments
            from docling.datamodel.base_models import InputFormat

            pdf_option = format_options[InputFormat.PDF]
            opts = pdf_option.pipeline_options
            assert opts.do_picture_description is True
            assert opts.do_code_enrichment is True
            assert opts.do_formula_enrichment is True
            assert opts.do_table_structure is True


class TestDoclingFormats:
    """Test the DOCLING_FORMATS set."""

    def test_docling_formats_contains_expected(self) -> None:
        from ragling.docling_convert import DOCLING_FORMATS

        expected = {
            "pdf",
            "docx",
            "pptx",
            "xlsx",
            "html",
            "latex",
            "image",
            "csv",
            "asciidoc",
            "vtt",
            "audio",
        }
        assert DOCLING_FORMATS == expected

    def test_markdown_not_in_docling_formats(self) -> None:
        from ragling.docling_convert import DOCLING_FORMATS

        assert "markdown" not in DOCLING_FORMATS

    def test_code_not_in_docling_formats(self) -> None:
        from ragling.docling_convert import DOCLING_FORMATS

        assert "code" not in DOCLING_FORMATS


class TestEnrichmentMetadata:
    """Tests for extracting enrichment metadata from doc_items."""

    def _make_chunker_with_items(self, doc_items: list) -> MagicMock:  # type: ignore[type-arg]
        """Helper: create mock chunker that returns one chunk with given doc_items."""
        mock_chunk = MagicMock()
        mock_chunk.meta.headings = ["Section"]
        mock_chunk.meta.doc_items = doc_items
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = [mock_chunk]
        mock_chunker.contextualize.return_value = "chunk text"
        return mock_chunker

    def test_extracts_picture_description(self, store: DocStore, sample_file: Path) -> None:
        from ragling.docling_convert import convert_and_chunk

        # Create a mock PictureItem with VLM description
        picture_item = MagicMock()
        picture_item.__class__.__name__ = "PictureItem"
        picture_item.caption_text.return_value = ""
        desc_meta = MagicMock()
        desc_meta.text = "A diagram showing system architecture"
        picture_item.meta.description = desc_meta

        mock_chunker = self._make_chunker_with_items([picture_item])

        with (
            patch("ragling.docling_convert._convert_with_docling"),
            patch.object(store, "get_or_convert", return_value={"name": "mock"}),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
            patch("ragling.docling_convert._is_picture_item", return_value=True),
            patch("ragling.docling_convert._is_table_item", return_value=False),
            patch("ragling.docling_convert._is_code_item", return_value=False),
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
            chunks = convert_and_chunk(sample_file, store)

        assert (
            chunks[0].metadata.get("picture_description") == "A diagram showing system architecture"
        )

    def test_extracts_caption(self, store: DocStore, sample_file: Path) -> None:
        from ragling.docling_convert import convert_and_chunk

        table_item = MagicMock()
        table_item.__class__.__name__ = "TableItem"
        table_item.caption_text.return_value = "Table 1: Results summary"

        mock_chunker = self._make_chunker_with_items([table_item])

        with (
            patch("ragling.docling_convert._convert_with_docling"),
            patch.object(store, "get_or_convert", return_value={"name": "mock"}),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
            patch("ragling.docling_convert._is_picture_item", return_value=False),
            patch("ragling.docling_convert._is_table_item", return_value=True),
            patch("ragling.docling_convert._is_code_item", return_value=False),
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
            chunks = convert_and_chunk(sample_file, store)

        assert chunks[0].metadata["captions"] == ["Table 1: Results summary"]

    def test_extracts_code_language(self, store: DocStore, sample_file: Path) -> None:
        from ragling.docling_convert import convert_and_chunk

        code_item = MagicMock()
        code_item.__class__.__name__ = "CodeItem"
        code_item.code_language.value = "python"

        mock_chunker = self._make_chunker_with_items([code_item])

        with (
            patch("ragling.docling_convert._convert_with_docling"),
            patch.object(store, "get_or_convert", return_value={"name": "mock"}),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
            patch("ragling.docling_convert._is_picture_item", return_value=False),
            patch("ragling.docling_convert._is_table_item", return_value=False),
            patch("ragling.docling_convert._is_code_item", return_value=True),
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
            chunks = convert_and_chunk(sample_file, store)

        assert chunks[0].metadata["code_language"] == "python"


class TestConfigHashPassthrough:
    """Tests that convert_and_chunk passes config_hash to doc_store."""

    def test_convert_and_chunk_passes_config_hash(self, store: DocStore, sample_file: Path) -> None:
        from ragling.docling_convert import convert_and_chunk

        with patch.object(store, "get_or_convert", return_value={"name": "mock"}) as mock_get:
            with patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls:
                mock_doc = MagicMock()
                mock_doc_cls.model_validate.return_value = mock_doc
                with patch("ragling.docling_convert._get_tokenizer") as mock_tok:
                    mock_tok.return_value = MagicMock()
                    with patch("ragling.docling_convert.HybridChunker") as mock_chunker_cls:
                        mock_chunker = MagicMock()
                        mock_chunker.chunk.return_value = []
                        mock_chunker_cls.return_value = mock_chunker

                        convert_and_chunk(sample_file, store)

            # Verify config_hash was passed
            call_kwargs = mock_get.call_args
            assert "config_hash" in call_kwargs.kwargs
            assert isinstance(call_kwargs.kwargs["config_hash"], str)
            assert len(call_kwargs.kwargs["config_hash"]) == 16
