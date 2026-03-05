"""Shared format routing for document indexers.

Maps file extensions to source types and routes files to the correct
parser/chunker pipeline. Used by ProjectIndexer, ObsidianIndexer, and
any indexer that handles mixed-format directories.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ragling.document.chunker import Chunk
from ragling.document.docling_bridge import (
    epub_to_docling_doc,
    markdown_to_docling_doc,
    plaintext_to_docling_doc,
)
from ragling.document.docling_convert import DOCLING_FORMATS, chunk_with_hybrid, convert_and_chunk
from ragling.parsers.code import get_supported_extensions as _get_code_extensions
from ragling.parsers.epub import parse_epub
from ragling.parsers.markdown import parse_markdown
from ragling.parsers.spec import is_spec_file, parse_spec

if TYPE_CHECKING:
    from ragling.config import Config
    from ragling.doc_store import DocStore

logger = logging.getLogger(__name__)

# Map file extensions to source types. Docling-handled formats go through
# convert_and_chunk(); legacy formats (markdown, epub, plaintext) go through
# dedicated parsers.
EXTENSION_MAP: dict[str, str] = {
    # Docling-handled formats
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".epub": "epub",
    ".txt": "plaintext",
    ".tex": "latex",
    ".latex": "latex",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".webp": "image",
    ".csv": "csv",
    ".adoc": "asciidoc",
    ".vtt": "vtt",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".aac": "audio",
    ".ogg": "audio",
    ".flac": "audio",
    ".opus": "audio",
    ".mp4": "audio",
    ".avi": "audio",
    ".mov": "audio",
    ".mkv": "audio",
    ".mka": "audio",
    # Legacy-handled formats
    ".md": "markdown",
    ".json": "plaintext",
    ".yaml": "plaintext",
    ".yml": "plaintext",
}

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(EXTENSION_MAP) | _get_code_extensions()


def is_supported_extension(ext: str) -> bool:
    """Check if a file extension is supported for indexing.

    Covers both document extensions (EXTENSION_MAP) and code extensions
    (get_supported_extensions() from parsers.code).

    Args:
        ext: File extension including the dot (e.g. ".pdf").

    Returns:
        True if the extension is supported for any indexing path.
    """
    return ext in SUPPORTED_EXTENSIONS


def parse_and_chunk(
    path: Path,
    source_type: str,
    config: Config,
    doc_store: DocStore | None = None,
    source_path: str | None = None,
) -> list[Chunk]:
    """Parse a file and return chunks based on its type.

    Routes the file to the correct parser/chunker pipeline based on
    source_type. Docling-handled formats go through convert_and_chunk();
    legacy formats use dedicated parsers with HybridChunker.

    Args:
        path: Path to the file.
        source_type: Detected source type (e.g. "markdown", "spec").
        config: Application configuration.
        doc_store: Optional shared document store for Docling conversion.
        source_path: Optional source path for context in chunk metadata.
            Used as the relative_path for SPEC.md parsing. Falls back to
            the filename if not provided.
    """
    # Route Docling-handled formats through Docling when doc_store is available
    if source_type in DOCLING_FORMATS:
        if doc_store is None:
            logger.error(
                "Format '%s' requires doc_store for Docling conversion but none was provided "
                "— this indicates a configuration error. Skipping %s",
                source_type,
                path,
            )
            return []
        return convert_and_chunk(
            path,
            doc_store,
            chunk_max_tokens=config.chunk_size_tokens,
            source_type=source_type,
            asr_model=config.asr.model,
            config=config,
        )

    # SPEC.md: parse with dedicated spec parser for section-level chunking.
    # Safe after the Docling check — "spec" and "markdown" are never in DOCLING_FORMATS.
    if is_spec_file(path) and source_type in ("spec", "markdown"):
        text = path.read_text(encoding="utf-8", errors="replace")
        spec_path = source_path or path.name
        return parse_spec(text, spec_path, chunk_size_tokens=config.chunk_size_tokens)

    # Markdown: parse with legacy parser (preserves Obsidian metadata), chunk with HybridChunker
    if source_type == "markdown":
        text = path.read_text(encoding="utf-8", errors="replace")
        doc = parse_markdown(text, path.name)
        docling_doc = markdown_to_docling_doc(doc.body_text, doc.title)
        extra_metadata: dict[str, list[str]] = {}
        if doc.tags:
            extra_metadata["tags"] = doc.tags
        if doc.links:
            extra_metadata["links"] = doc.links
        return chunk_with_hybrid(
            docling_doc,
            title=doc.title,
            source_path=str(path),
            extra_metadata=extra_metadata or None,
            chunk_max_tokens=config.chunk_size_tokens,
        )

    # EPUB: parse with legacy parser, chunk with HybridChunker
    if source_type == "epub":
        chapters = parse_epub(path)
        docling_doc = epub_to_docling_doc(chapters, path.name)
        return chunk_with_hybrid(
            docling_doc,
            title=path.name,
            source_path=str(path),
            chunk_max_tokens=config.chunk_size_tokens,
        )

    # Plaintext: build minimal DoclingDocument, chunk with HybridChunker
    if source_type == "plaintext":
        text = path.read_text(encoding="utf-8", errors="replace")
        docling_doc = plaintext_to_docling_doc(text, path.name)
        return chunk_with_hybrid(
            docling_doc,
            title=path.name,
            source_path=str(path),
            chunk_max_tokens=config.chunk_size_tokens,
        )

    logger.warning("Unknown source type '%s' for %s", source_type, path)
    return []
