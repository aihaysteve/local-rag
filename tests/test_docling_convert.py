"""Tests for ragling.docling_convert module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ragling.chunker import Chunk
from ragling.config import Config
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

        mock_chunk = MagicMock()
        mock_chunk.meta.headings = ["Section 1"]
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = [mock_chunk]
        mock_chunker.contextualize.return_value = "Section 1\nchunk text"

        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_result.document.model_dump.return_value = {
            "name": "mock",
            "schema_name": "DoclingDocument",
        }
        mock_converter.convert.return_value = mock_result

        with (
            patch("ragling.docling_convert.get_converter", return_value=mock_converter),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
            chunks = convert_and_chunk(sample_file, store)

        assert len(chunks) == 1
        assert isinstance(chunks[0], Chunk)
        assert chunks[0].text == "Section 1\nchunk text"
        assert chunks[0].title == "test.pdf"
        assert chunks[0].chunk_index == 0

    def test_chunk_metadata_includes_source_path(self, store: DocStore, sample_file: Path) -> None:
        from ragling.docling_convert import convert_and_chunk

        mock_chunk = MagicMock()
        mock_chunk.meta.headings = ["H1"]
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = [mock_chunk]
        mock_chunker.contextualize.return_value = "H1\ntext"

        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_result.document.model_dump.return_value = {"name": "mock"}
        mock_converter.convert.return_value = mock_result

        with (
            patch("ragling.docling_convert.get_converter", return_value=mock_converter),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
            chunks = convert_and_chunk(sample_file, store)

        assert chunks[0].metadata["source_path"] == str(sample_file)
        assert chunks[0].metadata["headings"] == ["H1"]

    def test_multiple_chunks_have_sequential_indices(
        self, store: DocStore, sample_file: Path
    ) -> None:
        from ragling.docling_convert import convert_and_chunk

        chunks_data = [MagicMock() for _ in range(3)]
        for i, mc in enumerate(chunks_data):
            mc.meta.headings = [f"Section {i}"]
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = chunks_data
        mock_chunker.contextualize.side_effect = [f"Section {i}\ntext {i}" for i in range(3)]

        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_result.document.model_dump.return_value = {"name": "mock"}
        mock_converter.convert.return_value = mock_result

        with (
            patch("ragling.docling_convert.get_converter", return_value=mock_converter),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
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


class TestChunkWithHybrid:
    """Tests for the shared chunk_with_hybrid function."""

    def test_returns_list_of_chunks(self) -> None:
        from ragling.docling_convert import chunk_with_hybrid

        mc = MagicMock()
        mc.meta.headings = ["H1"]
        mc.meta.doc_items = []
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = [mc]
        mock_chunker.contextualize.return_value = "contextualized text"

        with (
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
        ):
            chunks = chunk_with_hybrid(
                MagicMock(),
                title="test.md",
                source_path="/tmp/test.md",
            )

        assert len(chunks) == 1
        assert isinstance(chunks[0], Chunk)
        assert chunks[0].text == "contextualized text"
        assert chunks[0].metadata["source_path"] == "/tmp/test.md"

    def test_merges_extra_metadata(self) -> None:
        from ragling.docling_convert import chunk_with_hybrid

        mc = MagicMock()
        mc.meta.headings = []
        mc.meta.doc_items = []
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = [mc]
        mock_chunker.contextualize.return_value = "text"

        with (
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
        ):
            chunks = chunk_with_hybrid(
                MagicMock(),
                title="note.md",
                source_path="/tmp/note.md",
                extra_metadata={"tags": ["python", "rag"], "links": ["Other Note"]},
            )

        assert chunks[0].metadata["tags"] == ["python", "rag"]
        assert chunks[0].metadata["links"] == ["Other Note"]


class TestDescribeImage:
    """Tests for the describe_image() standalone image description helper."""

    def test_returns_description_string(self, tmp_path: Path) -> None:
        from ragling.docling_convert import describe_image

        # Create a minimal image file
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="red")
        img_path = tmp_path / "test.png"
        img.save(img_path)

        mock_engine = MagicMock()
        mock_output = MagicMock()
        mock_output.text = "A red square image"
        mock_engine.predict.return_value = mock_output

        with patch("ragling.docling_convert._get_vlm_engine", return_value=mock_engine):
            result = describe_image(img_path)

        assert result == "A red square image"

    def test_returns_empty_string_on_error(self, tmp_path: Path) -> None:
        from ragling.docling_convert import describe_image

        from PIL import Image

        img = Image.new("RGB", (10, 10))
        img_path = tmp_path / "bad.png"
        img.save(img_path)

        mock_engine = MagicMock()
        mock_engine.predict.side_effect = RuntimeError("model failed")

        with patch("ragling.docling_convert._get_vlm_engine", return_value=mock_engine):
            result = describe_image(img_path)

        assert result == ""

    def test_returns_empty_string_for_missing_file(self, tmp_path: Path) -> None:
        from ragling.docling_convert import describe_image

        result = describe_image(tmp_path / "nonexistent.png")
        assert result == ""


class TestConvertAndChunkImageFallback:
    """Tests for image fallback in convert_and_chunk."""

    def test_image_fallback_produces_chunks(self, store: DocStore, tmp_path: Path) -> None:
        """When Docling returns empty for an image, describe_image() fallback kicks in."""
        from ragling.docling_convert import convert_and_chunk

        # Create a real image file
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="blue")
        img_path = tmp_path / "photo.jpg"
        img.save(img_path)

        # Mock Docling returning an empty document
        empty_doc = MagicMock()
        empty_doc.export_to_text.return_value = ""

        # Mock HybridChunker returning no chunks for empty doc, then chunks for described doc
        mock_chunk = MagicMock()
        mock_chunk.meta.headings = []
        mock_chunk.meta.doc_items = []
        mock_chunker = MagicMock()
        mock_chunker.chunk.side_effect = [[], [mock_chunk]]  # empty first, then with content
        mock_chunker.contextualize.return_value = "Five kittens walking on grass"

        with (
            patch.object(store, "get_or_convert", return_value={"name": "mock"}),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
            patch(
                "ragling.docling_convert.describe_image",
                return_value="Five kittens walking on grass",
            ),
        ):
            mock_doc_cls.model_validate.return_value = empty_doc
            chunks = convert_and_chunk(img_path, store, source_type="image")

        assert len(chunks) == 1
        assert "kittens" in chunks[0].text

    def test_image_fallback_not_triggered_for_non_images(
        self, store: DocStore, tmp_path: Path
    ) -> None:
        """Non-image source types should not trigger the fallback."""
        from ragling.docling_convert import convert_and_chunk

        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        # Docling returns empty, but since it's a PDF, no fallback
        empty_doc = MagicMock()
        empty_doc.export_to_text.return_value = ""
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = []

        with (
            patch.object(store, "get_or_convert", return_value={"name": "mock"}),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
            patch("ragling.docling_convert.describe_image") as mock_describe,
        ):
            mock_doc_cls.model_validate.return_value = empty_doc
            chunks = convert_and_chunk(pdf_path, store)

        mock_describe.assert_not_called()
        assert len(chunks) == 0

    def test_image_fallback_not_triggered_when_docling_has_content(
        self, store: DocStore, tmp_path: Path
    ) -> None:
        """When Docling successfully extracts text from an image, no fallback needed."""
        from ragling.docling_convert import convert_and_chunk

        from PIL import Image

        img = Image.new("RGB", (100, 100))
        img_path = tmp_path / "scanned.png"
        img.save(img_path)

        mock_chunk = MagicMock()
        mock_chunk.meta.headings = ["OCR Text"]
        mock_chunk.meta.doc_items = []
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = [mock_chunk]
        mock_chunker.contextualize.return_value = "OCR extracted text"

        with (
            patch.object(store, "get_or_convert", return_value={"name": "mock"}),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
            patch("ragling.docling_convert.describe_image") as mock_describe,
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
            chunks = convert_and_chunk(img_path, store, source_type="image")

        mock_describe.assert_not_called()
        assert len(chunks) == 1


class TestAnyUrlSerialization:
    """Bug #1: Docling model_dump() returns AnyUrl objects that aren't JSON serializable."""

    def test_model_dump_called_with_json_mode(self, store: DocStore, sample_file: Path) -> None:
        """_do_convert must call model_dump(mode='json') to serialize AnyUrl to strings."""
        from ragling.docling_convert import convert_and_chunk

        mock_chunk = MagicMock()
        mock_chunk.meta.headings = ["Section"]
        mock_chunk.meta.doc_items = []
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = [mock_chunk]
        mock_chunker.contextualize.return_value = "chunk text"

        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_result.document.model_dump.return_value = {"name": "mock"}
        mock_converter.convert.return_value = mock_result

        with (
            patch("ragling.docling_convert.get_converter", return_value=mock_converter),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
            convert_and_chunk(sample_file, store)

        # Verify model_dump was called with mode="json" to avoid AnyUrl serialization issues
        mock_result.document.model_dump.assert_called_once_with(mode="json")


class TestConverterConfigHash:
    def test_includes_asr_model_in_hash(self) -> None:
        from ragling.docling_convert import converter_config_hash

        hash1 = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="accurate",
            asr_model="small",
        )
        hash2 = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="accurate",
            asr_model="turbo",
        )
        assert hash1 != hash2

    def test_hash_stable_for_same_config(self) -> None:
        from ragling.docling_convert import converter_config_hash

        hash1 = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="accurate",
            asr_model="small",
        )
        hash2 = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="accurate",
            asr_model="small",
        )
        assert hash1 == hash2


class TestAsrModelConfiguration:
    def test_get_converter_uses_configured_model(self) -> None:
        from ragling.docling_convert import get_converter

        get_converter.cache_clear()
        with (
            patch("ragling.docling_convert.DocumentConverter") as mock_cls,
            patch("ragling.docling_convert._whisper_available", return_value=True),
            patch("ragling.docling_convert._get_asr_model_spec") as mock_spec,
        ):
            mock_cls.return_value = MagicMock()
            mock_spec.return_value = MagicMock()
            get_converter(asr_model="turbo")
            mock_spec.assert_called_once_with("turbo")

    def test_get_asr_model_spec_returns_valid_spec(self) -> None:
        from ragling.docling_convert import _get_asr_model_spec

        spec = _get_asr_model_spec("small")
        # Should be some kind of ASR options object, not None
        assert spec is not None

    def test_get_asr_model_spec_falls_back_for_unknown(self) -> None:
        from ragling.docling_convert import _get_asr_model_spec

        spec = _get_asr_model_spec("nonexistent_model")
        # Should fall back to "small" rather than crashing
        small_spec = _get_asr_model_spec("small")
        assert spec == small_spec


class TestGetConverterAsr:
    def test_get_converter_includes_audio_format_option(self) -> None:
        from ragling.docling_convert import get_converter

        get_converter.cache_clear()
        with patch("ragling.docling_convert.DocumentConverter") as mock_cls:
            mock_cls.return_value = MagicMock()
            with patch("ragling.docling_convert._whisper_available", return_value=True):
                get_converter()
            call_kwargs = mock_cls.call_args.kwargs
            format_options = call_kwargs["format_options"]

            from docling.datamodel.base_models import InputFormat

            assert InputFormat.AUDIO in format_options

    def test_get_converter_skips_audio_when_whisper_missing(self) -> None:
        """When whisper is not installed, audio format should not be configured."""
        from ragling.docling_convert import get_converter

        get_converter.cache_clear()
        with (
            patch("ragling.docling_convert.DocumentConverter") as mock_cls,
            patch("ragling.docling_convert._whisper_available", return_value=False),
        ):
            mock_cls.return_value = MagicMock()
            get_converter()
            call_kwargs = mock_cls.call_args.kwargs
            format_options = call_kwargs["format_options"]

            from docling.datamodel.base_models import InputFormat

            assert InputFormat.AUDIO not in format_options


class TestAudioFormatRegistration:
    @pytest.mark.parametrize("ext", ["opus", "mkv", "mka"])
    def test_extra_extension_registered_as_audio(self, ext: str) -> None:
        from ragling.docling_convert import ensure_audio_formats_registered

        ensure_audio_formats_registered()

        from docling.datamodel.base_models import FormatToExtensions, InputFormat

        assert ext in FormatToExtensions[InputFormat.AUDIO]

    def test_idempotent(self) -> None:
        from ragling.docling_convert import ensure_audio_formats_registered

        ensure_audio_formats_registered()
        ensure_audio_formats_registered()  # should not raise or duplicate

        from docling.datamodel.base_models import FormatToExtensions, InputFormat

        count = FormatToExtensions[InputFormat.AUDIO].count("opus")
        assert count == 1


class TestConfigHashPassthrough:
    """Tests that convert_and_chunk passes config_hash to doc_store."""

    def test_convert_and_chunk_passes_config_hash(self, store: DocStore, sample_file: Path) -> None:
        from ragling.docling_convert import convert_and_chunk

        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = []

        with (
            patch.object(store, "get_or_convert", return_value={"name": "mock"}) as mock_get,
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
            convert_and_chunk(sample_file, store)

        call_kwargs = mock_get.call_args
        assert "config_hash" in call_kwargs.kwargs
        assert isinstance(call_kwargs.kwargs["config_hash"], str)
        assert len(call_kwargs.kwargs["config_hash"]) == 16


class TestAudioMetadataIntegration:
    def test_audio_chunks_include_container_metadata(self, store: DocStore, tmp_path: Path) -> None:
        """When source_type is 'audio', chunks should include container metadata."""
        from ragling.docling_convert import convert_and_chunk

        audio_file = tmp_path / "recording.mp3"
        audio_file.write_bytes(b"fake audio content")

        mock_chunk = MagicMock()
        mock_chunk.meta.headings = []
        mock_chunk.meta.doc_items = []
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = [mock_chunk]
        mock_chunker.contextualize.return_value = "Hello world transcription"

        mock_metadata = {
            "duration_seconds": 120.5,
            "title": "My Recording",
            "artist": "Steve",
        }

        with (
            patch.object(store, "get_or_convert", return_value={"name": "mock"}),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
            patch(
                "ragling.docling_convert.extract_audio_metadata",
                return_value=mock_metadata,
            ),
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
            chunks = convert_and_chunk(audio_file, store, source_type="audio")

        assert chunks[0].metadata["duration_seconds"] == 120.5
        assert chunks[0].metadata["title"] == "My Recording"
        assert chunks[0].metadata["artist"] == "Steve"

    def test_non_audio_chunks_skip_metadata_extraction(
        self, store: DocStore, sample_file: Path
    ) -> None:
        """PDF source_type should not trigger audio metadata extraction."""
        from ragling.docling_convert import convert_and_chunk

        mock_chunk = MagicMock()
        mock_chunk.meta.headings = []
        mock_chunk.meta.doc_items = []
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = [mock_chunk]
        mock_chunker.contextualize.return_value = "text"

        with (
            patch.object(store, "get_or_convert", return_value={"name": "mock"}),
            patch("ragling.docling_convert.DoclingDocument") as mock_doc_cls,
            patch("ragling.docling_convert._get_tokenizer", return_value=MagicMock()),
            patch("ragling.docling_convert.HybridChunker", return_value=mock_chunker),
            patch(
                "ragling.docling_convert.extract_audio_metadata",
            ) as mock_extract,
        ):
            mock_doc_cls.model_validate.return_value = MagicMock()
            convert_and_chunk(sample_file, store, source_type="pdf")

        mock_extract.assert_not_called()


class TestAudioGracefulDegradation:
    def test_audio_conversion_error_propagates(self, store: DocStore, tmp_path: Path) -> None:
        """Conversion errors for audio files propagate so callers can handle them."""
        from ragling.docling_convert import convert_and_chunk

        audio_file = tmp_path / "voice.mp3"
        audio_file.write_bytes(b"fake audio")

        with (
            patch.object(
                store,
                "get_or_convert",
                side_effect=ImportError("No module named 'whisper'"),
            ),
            pytest.raises(ImportError, match="whisper"),
        ):
            convert_and_chunk(audio_file, store, source_type="audio")

    def test_index_files_catches_audio_errors(self, tmp_path: Path) -> None:
        """The project indexer's _index_files loop catches audio conversion errors."""
        from ragling.db import get_connection, init_db
        from ragling.indexers.project import ProjectIndexer

        audio_file = tmp_path / "voice.mp3"
        audio_file.write_bytes(b"fake audio")

        config = Config(db_path=tmp_path / "test.db", chunk_size_tokens=256)
        conn = get_connection(config)
        init_db(conn, config)

        store = DocStore(tmp_path / "doc_store.sqlite")
        indexer = ProjectIndexer(collection_name="test", paths=[tmp_path], doc_store=store)

        with patch(
            "ragling.indexers.project.convert_and_chunk",
            side_effect=ImportError("No module named 'whisper'"),
        ):
            result = indexer._index_files(conn, config, [audio_file], 1, force=True)

        assert result.errors == 1
        assert result.indexed == 0
