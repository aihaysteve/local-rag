# Document

## Purpose

Document conversion, chunking, and format bridging for the indexing pipeline.
All external formats (PDF, DOCX, PPTX, XLSX, HTML, images, audio, markdown,
EPUB, plaintext, email, RSS) are normalised into `Chunk` objects via either
Docling's `HybridChunker` or word-based window splitting.

## Core Mechanism

`docling_convert.py` wraps Docling's `DocumentConverter` for format conversion
and `HybridChunker` for structure-aware chunking. `get_converter()` is an
`lru_cache` singleton configured per enrichment settings. `convert_and_chunk()`
integrates with DocStore for content-addressed caching, with fallbacks for PDF
(pypdfium2 text extraction) and standalone images (VLM description via SmolVLM
or Ollama). `converter_config_hash()` produces a deterministic hash of pipeline
settings so changing enrichments invalidates cached conversions.

`docling_bridge.py` converts legacy parser output (markdown, epub, plaintext,
email, RSS) into `DoclingDocument` objects so all formats can be chunked by
`HybridChunker` with `contextualize()`. Each bridge function
(`markdown_to_docling_doc`, `epub_to_docling_doc`, etc.) preserves heading
hierarchy and paragraph structure.

`chunker.py` defines the `Chunk` dataclass (text, title, metadata,
chunk_index) and `split_into_windows()` for word-based overlapping window
splitting.

`audio_metadata.py` extracts container metadata (title, artist, album,
duration) from audio and video files via mutagen.

**Key files:**
- `chunker.py` -- Chunk dataclass and window splitting
- `docling_convert.py` -- Docling conversion, HybridChunker, VLM fallbacks
- `docling_bridge.py` -- legacy parser output to DoclingDocument bridge
- `audio_metadata.py` -- audio/video container metadata extraction via mutagen

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| `Chunk` | Indexers, parsers | Dataclass with text, title, metadata, chunk_index |
| `split_into_windows(text, size, overlap)` | Parsers (spec.py) | Returns `list[Chunk]` of overlapping word windows |
| `word_count(text)` | Parsers (spec.py) | Returns integer word count |
| `convert_and_chunk(path, doc_store, config, ...)` | Indexers (Obsidian, Project, Calibre) | Docling conversion with DocStore caching + HybridChunker; returns `list[Chunk]` |
| `chunk_with_hybrid(doc, ...)` | Indexers, `convert_and_chunk()` | Chunks a DoclingDocument via HybridChunker with `contextualize()`; returns `list[Chunk]` |
| `converter_config_hash(config)` | Indexers | Deterministic hash of pipeline settings for DocStore cache keying |
| `DOCLING_FORMATS` | Indexers, MCP server | Frozenset of file extensions supported by Docling |
| `markdown_to_docling_doc(text, title)` | Indexers (Obsidian, Project) | Bridge: markdown text to DoclingDocument |
| `epub_to_docling_doc(chapters, title)` | Indexers (Obsidian, Project) | Bridge: EPUB chapters to DoclingDocument |
| `plaintext_to_docling_doc(text, title)` | Indexers (Project) | Bridge: plain text to DoclingDocument |
| `email_to_docling_doc(subject, body)` | Indexers (Email) | Bridge: email content to DoclingDocument |
| `rss_to_docling_doc(title, body)` | Indexers (RSS) | Bridge: RSS article to DoclingDocument |
| `extract_audio_metadata(path)` | Indexers (Obsidian, Project) | Returns dict of audio/video metadata or empty dict on failure |

## Invariants

None moved from Core. Document-specific invariants are covered by the modules'
internal logic (e.g. `lru_cache` singleton for converter, content-addressed
caching via DocStore).

## Failure Modes

None moved from Core. Document conversion failures are handled internally:
`convert_and_chunk()` falls back to pypdfium2 for PDF and VLM for images;
bridge functions raise only on programmer error.

## Testing

```bash
uv run pytest tests/test_chunker.py tests/test_docling_convert.py \
  tests/test_docling_bridge.py tests/test_audio_metadata.py \
  tests/test_converter_config.py -v
```

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| `doc_store.py` (DocStore) | internal | `src/ragling/SPEC.md` |
| Docling | external | N/A -- document conversion (PDF, DOCX, etc.) |
| mutagen | external | N/A -- audio/video metadata extraction |
