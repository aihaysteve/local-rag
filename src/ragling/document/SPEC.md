# Document

## Purpose

Document conversion, chunking, and format bridging for the indexing pipeline.
All external formats (PDF, DOCX, PPTX, XLSX, HTML, images, audio, markdown,
EPUB, plaintext, email, RSS) are normalised into `Chunk` objects via either
Docling's `HybridChunker` or word-based window splitting.

## Core Mechanism

All external formats are normalized into `Chunk` objects via Docling's
`HybridChunker` or word-based window splitting. Formats not natively supported
by Docling are bridged into `DoclingDocument` objects so every format flows
through the same chunking pipeline.

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

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-1 | Docling `DocumentConverter` is a process-wide singleton via `lru_cache` on `get_converter()` | Creating multiple converters wastes memory and initialization time; singleton ensures consistent pipeline settings |
| INV-2 | `convert_and_chunk()` requires a `DocStore` for Docling-handled formats | Content-addressed caching prevents redundant conversions; callers must provide a DocStore or get an error log and empty result |
| INV-3 | `split_into_windows()` returns non-empty output for non-empty input | Downstream code assumes at least one chunk per non-empty text; empty output would produce sources with zero documents |
| INV-4 | Audio metadata extraction is best-effort — failures return empty dict, never raise | One corrupt audio file must not abort an indexing batch |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-1 | `convert_and_chunk()` returns chunks from pypdfium2 text instead of Docling | Primary Docling conversion failed (corrupted PDF, missing fonts) | Automatic fallback; quality may be reduced — re-index if the source file is fixed |
| FAIL-2 | `ValueError` raised from `convert_and_chunk()` | Unsupported `source_type` passed (not in `DOCLING_FORMATS`) | Programming error in caller — check `DOCLING_FORMATS` before calling |
| FAIL-3 | `extract_audio_metadata()` returns empty dict | Corrupt or unsupported audio container | File is logged and skipped; metadata fields will be empty in search results |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| `doc_store.py` (DocStore) | internal | `src/ragling/SPEC.md` |
| Docling | external | N/A -- document conversion (PDF, DOCX, etc.) |
| mutagen | external | N/A -- audio/video metadata extraction |
