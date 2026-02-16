"""Docling document conversion and chunking wrapper.

Wraps Docling's DocumentConverter for format conversion and
HybridChunker for structure-aware chunking. Integrates with
DocStore for content-addressed caching.
"""

import hashlib as _hashlib
import json as _json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

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
from docling_core.types.doc import DoclingDocument
from transformers import AutoTokenizer

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
) -> str:
    """Deterministic hash of converter pipeline configuration.

    Used as part of the doc_store cache key so that changing
    enrichment settings automatically invalidates cached conversions.

    Args:
        do_picture_description: Whether VLM picture descriptions are enabled.
        do_code_enrichment: Whether code block extraction is enabled.
        do_formula_enrichment: Whether formula LaTeX extraction is enabled.
        table_mode: Table extraction mode (e.g. ``"accurate"`` or ``"fast"``).

    Returns:
        A 16-character hex string derived from SHA-256.
    """
    config_repr = _json.dumps(
        {
            "do_picture_description": do_picture_description,
            "do_code_enrichment": do_code_enrichment,
            "do_formula_enrichment": do_formula_enrichment,
            "table_mode": table_mode,
        },
        sort_keys=True,
    )
    return _hashlib.sha256(config_repr.encode()).hexdigest()[:16]


@lru_cache
def get_converter() -> DocumentConverter:
    """Get or create the Docling DocumentConverter singleton.

    Configures the PDF pipeline with all enrichments:
    - Picture descriptions via SmolVLM
    - Code block extraction via codeformulav2
    - Formula (LaTeX) extraction via codeformulav2
    - Accurate table structure extraction
    """
    pdf_options = PdfPipelineOptions(
        do_table_structure=True,
        table_structure_options=TableStructureOptions(
            mode=TableFormerMode.ACCURATE,
            do_cell_matching=True,
        ),
        do_picture_description=True,
        picture_description_options=PictureDescriptionVlmEngineOptions.from_preset("smolvlm"),
        do_code_enrichment=True,
        do_formula_enrichment=True,
        code_formula_options=CodeFormulaVlmOptions.from_preset("codeformulav2"),
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=StandardPdfPipeline,
                pipeline_options=pdf_options,
            )
        }
    )


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


def _convert_with_docling(path: Path) -> dict[str, Any]:
    """Convert a file using Docling and return serializable dict.

    Args:
        path: Path to the document file.

    Returns:
        A JSON-serializable dict representation of the DoclingDocument.
    """
    result = get_converter().convert(str(path))
    doc = result.document
    return doc.model_dump()


def convert_and_chunk(
    path: Path,
    doc_store: DocStore,
    chunk_max_tokens: int = 256,
    embedding_model_id: str = "BAAI/bge-m3",
) -> list[Chunk]:
    """Convert a document via Docling (cached in doc_store), chunk with HybridChunker.

    Args:
        path: Path to the source document.
        doc_store: Shared document store for caching conversions.
        chunk_max_tokens: Maximum tokens per chunk.
        embedding_model_id: HuggingFace model ID for tokenizer alignment.

    Returns:
        List of Chunk dataclass instances ready for embedding.
    """
    # 1. Get or convert (content-addressed via doc_store)
    doc_data = doc_store.get_or_convert(path, _convert_with_docling)

    # 2. Reconstruct DoclingDocument from cached data
    doc = DoclingDocument.model_validate(doc_data)

    # 3. Chunk with HybridChunker
    tokenizer = _get_tokenizer(embedding_model_id, chunk_max_tokens)
    chunker = HybridChunker(tokenizer=tokenizer)
    doc_chunks = list(chunker.chunk(doc))

    # 4. Map to ragling Chunk format
    chunks: list[Chunk] = []
    for i, dc in enumerate(doc_chunks):
        headings: list[str] = getattr(dc.meta, "headings", None) or []
        chunks.append(
            Chunk(
                text=chunker.contextualize(dc),
                title=path.name,
                metadata={
                    "headings": headings,
                    "source_path": str(path),
                },
                chunk_index=i,
            )
        )

    return chunks
