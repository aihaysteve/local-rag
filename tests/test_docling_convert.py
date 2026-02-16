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
        }
        assert DOCLING_FORMATS == expected

    def test_markdown_not_in_docling_formats(self) -> None:
        from ragling.docling_convert import DOCLING_FORMATS

        assert "markdown" not in DOCLING_FORMATS

    def test_code_not_in_docling_formats(self) -> None:
        from ragling.docling_convert import DOCLING_FORMATS

        assert "code" not in DOCLING_FORMATS
