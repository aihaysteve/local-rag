"""Docling document conversion and chunking wrapper.

Wraps Docling's DocumentConverter for format conversion and
HybridChunker for structure-aware chunking. Integrates with
DocStore for content-addressed caching.
"""

from __future__ import annotations

import hashlib as _hashlib
import json as _json
import logging
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ragling.config import Config

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    CodeFormulaVlmOptions,
    PdfPipelineOptions,
    PictureDescriptionVlmEngineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc import CodeItem, DoclingDocument, PictureItem, TableItem
from transformers import AutoTokenizer

from docling.exceptions import ConversionError
from ragling.audio_metadata import extract_audio_metadata
from ragling.chunker import Chunk
from ragling.doc_store import DocStore

logger = logging.getLogger(__name__)

# Formats that Docling handles (vs. legacy parsers)
DOCLING_FORMATS: frozenset[str] = frozenset(
    {
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
)


def converter_config_hash(
    *,
    do_picture_description: bool,
    do_code_enrichment: bool,
    do_formula_enrichment: bool,
    table_mode: str,
    asr_model: str = "small",
) -> str:
    """Deterministic hash of converter pipeline configuration.

    Used as part of the doc_store cache key so that changing
    enrichment settings automatically invalidates cached conversions.

    Args:
        do_picture_description: Whether VLM picture descriptions are enabled.
        do_code_enrichment: Whether code block extraction is enabled.
        do_formula_enrichment: Whether formula LaTeX extraction is enabled.
        table_mode: Table extraction mode (e.g. ``"accurate"`` or ``"fast"``).
        asr_model: Whisper model name for audio transcription.

    Returns:
        A 16-character hex string derived from SHA-256.
    """
    config_repr = _json.dumps(
        {
            "asr_model": asr_model,
            "do_picture_description": do_picture_description,
            "do_code_enrichment": do_code_enrichment,
            "do_formula_enrichment": do_formula_enrichment,
            "table_mode": table_mode,
        },
        sort_keys=True,
    )
    return _hashlib.sha256(config_repr.encode()).hexdigest()[:16]


_EXTRA_AUDIO_EXTENSIONS = ["opus", "mkv", "mka"]
_EXTRA_AUDIO_MIMETYPES = [
    "audio/opus",
    "video/x-matroska",
    "audio/x-matroska",
]


def ensure_audio_formats_registered() -> None:
    """Register additional audio extensions with Docling's format registry.

    Docling's built-in ``FormatToExtensions`` doesn't include opus, mkv, or mka.
    This adds them so ``DocumentConverter.convert()`` auto-detects them as audio.
    Safe to call multiple times — skips already-registered extensions.
    """
    from docling.datamodel.base_models import (
        FormatToExtensions,
        FormatToMimeType,
        InputFormat,
    )

    existing_exts = FormatToExtensions[InputFormat.AUDIO]
    for ext in _EXTRA_AUDIO_EXTENSIONS:
        if ext not in existing_exts:
            existing_exts.append(ext)

    existing_mimes = FormatToMimeType.get(InputFormat.AUDIO, [])
    for mime in _EXTRA_AUDIO_MIMETYPES:
        if mime not in existing_mimes:
            existing_mimes.append(mime)


def _whisper_available() -> bool:
    """Check if any Whisper backend is installed."""
    try:
        import whisper  # type: ignore[import-not-found]  # noqa: F401

        return True
    except ImportError:
        pass
    try:
        import mlx_whisper  # type: ignore[import-untyped]  # noqa: F401

        return True
    except ImportError:
        pass
    return False


def _get_asr_model_spec(model_name: str) -> Any:
    """Map a model name string to a Docling ASR model spec.

    Args:
        model_name: One of 'tiny', 'small', 'medium', 'base', 'large', 'turbo'.

    Returns:
        The corresponding ``asr_model_specs`` constant.
    """
    from docling.datamodel import asr_model_specs

    specs = {
        "tiny": asr_model_specs.WHISPER_TINY,
        "small": asr_model_specs.WHISPER_SMALL,
        "medium": asr_model_specs.WHISPER_MEDIUM,
        "base": asr_model_specs.WHISPER_BASE,
        "large": asr_model_specs.WHISPER_LARGE,
        "turbo": asr_model_specs.WHISPER_TURBO,
    }
    spec = specs.get(model_name)
    if spec is None:
        logger.warning("Unknown ASR model '%s', falling back to 'small'", model_name)
        spec = asr_model_specs.WHISPER_SMALL
    return spec


@lru_cache
def get_converter(
    asr_model: str = "small",
    do_picture_description: bool = True,
    do_code_enrichment: bool = True,
    do_formula_enrichment: bool = True,
    do_table_structure: bool = True,
) -> DocumentConverter:
    """Get or create the Docling DocumentConverter singleton.

    Configures the PDF pipeline with the specified enrichments, and
    optionally the ASR pipeline for audio transcription when
    Whisper is installed.

    Args:
        asr_model: Whisper model size name (tiny/small/medium/base/large/turbo).
        do_picture_description: Whether VLM picture descriptions are enabled.
        do_code_enrichment: Whether code block extraction is enabled.
        do_formula_enrichment: Whether formula LaTeX extraction is enabled.
        do_table_structure: Whether table structure extraction is enabled.
    """
    pdf_options = PdfPipelineOptions(
        do_table_structure=do_table_structure,
        table_structure_options=TableStructureOptions(
            mode=TableFormerMode.FAST,
            do_cell_matching=True,
        ),
        do_picture_description=do_picture_description,
        picture_description_options=PictureDescriptionVlmEngineOptions.from_preset("smolvlm"),
        do_code_enrichment=do_code_enrichment,
        do_formula_enrichment=do_formula_enrichment,
        code_formula_options=CodeFormulaVlmOptions.from_preset("codeformulav2"),
    )

    format_options: dict[InputFormat, Any] = {
        InputFormat.PDF: PdfFormatOption(
            pipeline_cls=StandardPdfPipeline,
            pipeline_options=pdf_options,
        )
    }

    if _whisper_available():
        ensure_audio_formats_registered()
        from docling.datamodel.pipeline_options import AsrPipelineOptions
        from docling.document_converter import AudioFormatOption

        asr_options = AsrPipelineOptions()
        asr_options.asr_options = _get_asr_model_spec(asr_model)

        format_options[InputFormat.AUDIO] = AudioFormatOption(
            pipeline_options=asr_options,
        )
        logger.info("ASR pipeline enabled with model '%s'", asr_model)
    else:
        logger.info("ASR pipeline disabled (no Whisper backend installed)")

    return DocumentConverter(format_options=format_options)


@lru_cache
def _get_tokenizer(model_id: str, max_tokens: int) -> HuggingFaceTokenizer:
    """Create and cache a HuggingFace tokenizer wrapper for chunking.

    Args:
        model_id: HuggingFace model ID (e.g. ``BAAI/bge-m3``).
        max_tokens: Maximum tokens per chunk.

    Returns:
        A ``HuggingFaceTokenizer`` instance for use with ``HybridChunker``.
    """
    hf_tok = AutoTokenizer.from_pretrained(model_id)
    return HuggingFaceTokenizer(tokenizer=hf_tok, max_tokens=max_tokens)


def _is_picture_item(item: object) -> bool:
    """Check if a doc_item is a PictureItem."""
    return isinstance(item, PictureItem)


def _is_table_item(item: object) -> bool:
    """Check if a doc_item is a TableItem."""
    return isinstance(item, TableItem)


def _is_code_item(item: object) -> bool:
    """Check if a doc_item is a CodeItem."""
    return isinstance(item, CodeItem)


@lru_cache
def _get_vlm_engine() -> Any:
    """Get or create a cached VLM engine for standalone image description.

    Uses SmolVLM (same model as PDF picture descriptions) via Docling's
    engine factory. Lazy-loaded on first call, cached for process lifetime.

    Returns:
        A VLM engine instance with ``predict()`` method.
    """
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.models.inference_engines.vlm import create_vlm_engine

    options = PictureDescriptionVlmEngineOptions.from_preset("smolvlm")
    return create_vlm_engine(
        options=options.engine_options,
        model_spec=options.model_spec,
        artifacts_path=None,
        accelerator_options=AcceleratorOptions(),
        enable_remote_services=False,
    )


def _extract_pdf_text_fallback(path: Path) -> str:
    """Extract text from a PDF using pypdfium2 when Docling fails.

    Reads each page sequentially and concatenates text with page
    separators. Used as a fallback when Docling's PDF pipeline
    can't parse a file (e.g. inherited page dimensions).

    Args:
        path: Path to the PDF file.

    Returns:
        Extracted text, or empty string on failure.
    """
    try:
        import pypdfium2 as pdfium  # type: ignore[import-untyped]

        doc = pdfium.PdfDocument(str(path))
        pages: list[str] = []
        for i in range(len(doc)):
            page = doc[i]
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            if text.strip():
                pages.append(text)
        return "\n\n".join(pages)
    except Exception:
        logger.exception("pypdfium2 fallback also failed for %s", path)
        return ""


def describe_image(path: Path) -> str:
    """Generate a text description of a standalone image using SmolVLM.

    Workaround for Docling's limitation where standalone images don't
    receive VLM enrichment (only images embedded in PDFs do).

    Args:
        path: Path to an image file (PNG, JPG, TIFF, BMP, WEBP).

    Returns:
        A text description of the image, or empty string on failure.
    """
    if not path.exists():
        logger.warning("Image file not found: %s", path)
        return ""

    try:
        from PIL import Image

        from docling.models.inference_engines.vlm import VlmEngineInput

        engine = _get_vlm_engine()
        image = Image.open(path)
        result = engine.predict(
            VlmEngineInput(
                image=image,
                prompt="Describe this image in a few sentences.",
                max_new_tokens=200,
            )
        )
        return result.text
    except Exception:
        logger.exception("Failed to describe image: %s", path)
        return ""


def chunk_with_hybrid(
    doc: DoclingDocument,
    *,
    title: str,
    source_path: str,
    extra_metadata: dict[str, Any] | None = None,
    chunk_max_tokens: int = 256,
    embedding_model_id: str = "BAAI/bge-m3",
) -> list[Chunk]:
    """Chunk a DoclingDocument using HybridChunker with contextualize().

    Shared by both the Docling conversion path and the legacy-parser bridge path.

    Args:
        doc: A DoclingDocument (from Docling conversion or built via bridge).
        title: Title to use for each Chunk.
        source_path: Source file path stored in chunk metadata.
        extra_metadata: Additional metadata to merge into every chunk
            (e.g. Obsidian tags, wikilinks).
        chunk_max_tokens: Maximum tokens per chunk.
        embedding_model_id: HuggingFace model ID for tokenizer alignment.

    Returns:
        List of Chunk dataclass instances.
    """
    tokenizer = _get_tokenizer(embedding_model_id, chunk_max_tokens)
    chunker = HybridChunker(tokenizer=tokenizer)
    doc_chunks = list(chunker.chunk(doc))

    if not doc_chunks:
        logger.debug("HybridChunker produced 0 chunks for '%s' (%s)", title, source_path)

    chunks: list[Chunk] = []
    for i, dc in enumerate(doc_chunks):
        headings: list[str] = getattr(dc.meta, "headings", None) or []
        metadata: dict[str, Any] = {
            "headings": headings,
            "source_path": source_path,
        }

        # Extract enrichment metadata from doc_items (only present for Docling-converted docs)
        for doc_item in getattr(dc.meta, "doc_items", []):
            if _is_picture_item(doc_item):
                caption = doc_item.caption_text(doc)
                if caption:
                    metadata.setdefault("captions", []).append(caption)
                if getattr(doc_item, "meta", None) and getattr(doc_item.meta, "description", None):
                    metadata["picture_description"] = doc_item.meta.description.text
            elif _is_table_item(doc_item):
                caption = doc_item.caption_text(doc)
                if caption:
                    metadata.setdefault("captions", []).append(caption)
            elif _is_code_item(doc_item):
                lang = getattr(doc_item, "code_language", None)
                if lang:
                    metadata["code_language"] = lang.value

        if extra_metadata:
            metadata.update(extra_metadata)

        chunks.append(
            Chunk(
                text=chunker.contextualize(dc),
                title=title,
                metadata=metadata,
                chunk_index=i,
            )
        )

    return chunks


def convert_and_chunk(
    path: Path,
    doc_store: DocStore,
    chunk_max_tokens: int = 256,
    embedding_model_id: str = "BAAI/bge-m3",
    source_type: str | None = None,
    asr_model: str = "small",
    *,
    config: Config | None = None,
) -> list[Chunk]:
    """Convert a document via Docling (cached in doc_store), chunk with HybridChunker.

    For standalone image files, if Docling returns empty content (a known
    limitation), falls back to generating a VLM description with SmolVLM.

    Args:
        path: Path to the source document.
        doc_store: Shared document store for caching conversions.
        chunk_max_tokens: Maximum tokens per chunk.
        embedding_model_id: HuggingFace model ID for tokenizer alignment.
        source_type: Optional source type hint (e.g. ``"image"``). When set
            to ``"image"`` and Docling produces no chunks, the VLM fallback
            is triggered.
        asr_model: Whisper model size for audio transcription.
        config: Optional application configuration. When provided, enrichment
            flags are read from ``config.enrichments``. Falls back to all
            enrichments enabled when ``None``.

    Returns:
        List of Chunk dataclass instances ready for embedding.
    """
    from ragling.config import EnrichmentConfig

    enrichments = config.enrichments if config is not None else EnrichmentConfig()

    config_hash = converter_config_hash(
        do_picture_description=enrichments.image_description,
        do_code_enrichment=enrichments.code_enrichment,
        do_formula_enrichment=enrichments.formula_enrichment,
        table_mode="fast",
        asr_model=asr_model,
    )

    def _do_convert(p: Path) -> dict[str, Any]:
        try:
            result = get_converter(
                asr_model=asr_model,
                do_picture_description=enrichments.image_description,
                do_code_enrichment=enrichments.code_enrichment,
                do_formula_enrichment=enrichments.formula_enrichment,
                do_table_structure=enrichments.table_structure,
            ).convert(p)
            return result.document.model_dump(mode="json")
        except ConversionError:
            if source_type != "pdf":
                raise
            logger.warning(
                "Docling PDF conversion failed for %s, falling back to pypdfium2 text extraction",
                p,
            )
            text = _extract_pdf_text_fallback(p)
            if not text.strip():
                raise
            from ragling.docling_bridge import plaintext_to_docling_doc

            return plaintext_to_docling_doc(text, p.name).model_dump(mode="json")

    doc_data = doc_store.get_or_convert(path, _do_convert, config_hash=config_hash)
    doc = DoclingDocument.model_validate(doc_data)

    chunks = chunk_with_hybrid(
        doc,
        title=path.name,
        source_path=str(path),
        chunk_max_tokens=chunk_max_tokens,
        embedding_model_id=embedding_model_id,
    )

    # Audio metadata: extract container tags and attach to chunks
    if source_type == "audio" and chunks:
        audio_meta = extract_audio_metadata(path)
        if audio_meta:
            for chunk in chunks:
                chunk.metadata.update(audio_meta)

    # Standalone image fallback: Docling's image pipeline doesn't run VLM
    # enrichment, so photos/diagrams produce zero chunks. Use SmolVLM directly.
    if not chunks and source_type == "image":
        description = describe_image(path)
        if description:
            logger.info("Image fallback: generated VLM description for %s", path)
            from ragling.docling_bridge import plaintext_to_docling_doc

            desc_doc = plaintext_to_docling_doc(description, path.name)
            chunks = chunk_with_hybrid(
                desc_doc,
                title=path.name,
                source_path=str(path),
                extra_metadata={"image_description": True},
                chunk_max_tokens=chunk_max_tokens,
                embedding_model_id=embedding_model_id,
            )

    return chunks
