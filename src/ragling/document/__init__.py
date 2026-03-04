"""Document conversion, chunking, and format bridging.

Re-exports for external consumers.  Internal code imports from submodules
directly (e.g. ``from ragling.document.chunker import ...``) so that test
``patch()`` targets resolve to the defining module.
"""

from ragling.document.audio_metadata import extract_audio_metadata
from ragling.document.chunker import Chunk, split_into_windows, word_count
from ragling.document.docling_bridge import (
    email_to_docling_doc,
    epub_to_docling_doc,
    markdown_to_docling_doc,
    plaintext_to_docling_doc,
    rss_to_docling_doc,
)
from ragling.document.docling_convert import (
    DOCLING_FORMATS,
    chunk_with_hybrid,
    convert_and_chunk,
    converter_config_hash,
)

__all__ = [
    "Chunk",
    "DOCLING_FORMATS",
    "chunk_with_hybrid",
    "convert_and_chunk",
    "converter_config_hash",
    "email_to_docling_doc",
    "epub_to_docling_doc",
    "extract_audio_metadata",
    "markdown_to_docling_doc",
    "plaintext_to_docling_doc",
    "rss_to_docling_doc",
    "split_into_windows",
    "word_count",
]
