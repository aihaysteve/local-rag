"""Document conversion, chunking, and format bridging.

Re-exports for external consumers.  Internal code imports from submodules
directly (e.g. ``from ragling.document.chunker import ...``) so that test
``patch()`` targets resolve to the defining module.

Heavy dependencies (docling, docling_core, transformers) are loaded lazily
via ``__getattr__`` to avoid triggering expensive imports when only lightweight
types like ``Chunk`` are needed.
"""

from ragling.document.audio_metadata import extract_audio_metadata
from ragling.document.chunker import Chunk, split_into_windows, word_count

# Lazy-loaded names from heavy submodules
_DOCLING_BRIDGE_NAMES = {
    "email_to_docling_doc",
    "epub_to_docling_doc",
    "markdown_to_docling_doc",
    "plaintext_to_docling_doc",
    "rss_to_docling_doc",
}

_DOCLING_CONVERT_NAMES = {
    "DOCLING_FORMATS",
    "chunk_with_hybrid",
    "convert_and_chunk",
    "converter_config_hash",
}


def __getattr__(name: str) -> object:
    if name in _DOCLING_BRIDGE_NAMES:
        from ragling.document import docling_bridge

        return getattr(docling_bridge, name)
    if name in _DOCLING_CONVERT_NAMES:
        from ragling.document import docling_convert

        return getattr(docling_convert, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
