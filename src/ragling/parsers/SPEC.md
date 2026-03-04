# Parsers

## Purpose

Format-specific content extraction for indexing. Each parser converts an external
data source into a structured domain object that indexers consume. Parsers validate
input, extract text, clean content, enrich with metadata, and return typed objects.
All parsers are read-only — they never modify source data.

The key design decision: parsers return domain-specific dataclasses (not raw text),
letting indexers handle chunking and embedding. The one exception is `spec.py`,
which produces `Chunk` objects directly because SPEC.md section structure maps
naturally to chunk boundaries.

## Core Mechanism

All parsers follow a consistent pattern: validate input, extract structure, clean
text, enrich metadata, return domain object. Errors are caught and logged — parsers
never raise exceptions to callers, returning `None` or empty collections instead.

**Key files:**
- `__init__.py` -- `open_ro()` utility for read-only SQLite access
- `markdown.py` -- Obsidian-flavored markdown with frontmatter, wikilinks, tags
- `epub.py` -- EPUB chapter extraction via ZIP archive, OPF manifest, and spine order
- `email.py` -- eM Client SQLite database parsing (.NET ticks, address types, FTI)
- `calibre.py` -- Calibre library metadata loading from metadata.db
- `code.py` -- Tree-sitter structural code parsing (48 extensions + 2 filename patterns, 36 languages). Symbol name extraction and symbol type classification use registry-based dispatch for extensibility.
- `rss.py` -- NetNewsWire RSS article parsing from DB.sqlite3 and FeedMetadata.plist
- `spec.py` -- SPEC.md section-level chunking into typed Chunk objects

**Parser output types:**
- `markdown.py` returns `MarkdownDocument` (title, body_text, frontmatter, tags, links)
- `epub.py` returns `list[tuple[int, str]]` (chapter_number, text) ordered by OPF spine
- `email.py` yields `Iterator[EmailMessage]` (subject, body, sender, recipients, date, folder)
- `calibre.py` returns `list[CalibreBook]` (full metadata: authors, tags, series, formats)
- `code.py` returns `CodeDocument | None` containing `CodeBlock` objects per structural unit
- `rss.py` yields `Iterator[Article]` (title, body, url, feed_name, authors, date)
- `spec.py` returns `list[Chunk]` with subsystem_name, section_type, spec_path metadata

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| `open_ro(db_path)` | email.py, calibre.py, rss.py | Opens SQLite in read-only mode (`?mode=ro`), returns `Connection` or `None` on failure |
| `parse_markdown(text, filename)` | project indexer | Returns `MarkdownDocument` with extracted frontmatter, wikilinks, tags |
| `parse_epub(path)` | calibre indexer, project indexer | Returns `list[tuple[int, str]]` of (chapter_number, text) in spine order |
| `parse_emails(account_dir, since_date?)` | email indexer | Yields `EmailMessage` objects; `since_date` filters by .NET ticks |
| `parse_calibre_library(library_path)` | calibre indexer | Returns `list[CalibreBook]` with full metadata from metadata.db |
| `parse_code_file(file_path, language, relative_path)` | git indexer | Returns `CodeDocument` with structural `CodeBlock` list, or `None` on failure |
| `parse_articles(account_dir, since_ts?)` | RSS indexer | Yields `Article` objects; `since_ts` filters by Unix timestamp |
| `parse_spec(text, relative_path, chunk_size_tokens?)` | git indexer, project indexer | Returns `list[Chunk]` with section-level metadata (subsystem, section_type, spec_path) |
| `find_nearest_spec(file_path, repo_root)` | git indexer | Walks up directory tree to find nearest SPEC.md, returns relative path or `None` |
| `is_spec_file(path)` | git indexer, project indexer | Returns `True` if filename is exactly `SPEC.md` (case-sensitive) |
| `is_code_file(path)` | git indexer, project indexer | Returns `True` if extension or filename matches a supported code language |
| `get_language(path)` | git indexer | Returns tree-sitter language name string, or `None` for unsupported files |

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-1 | All SQLite databases opened in read-only mode (`?mode=ro` URI) | Prevents accidental writes to eM Client, Calibre, and NetNewsWire databases |
| INV-2 | UTF-8 decoding uses `errors="replace"` for binary content | Graceful handling of malformed bytes in EPUB chapters and code files |
| INV-3 | Code blocks use 1-based line numbers (converted from tree-sitter's 0-based) | Matches human-readable file line numbers for search results and navigation |
| INV-4 | SPEC.md H2 headings must match `_SECTION_MAP` keys for correct section_type | Unknown headings get section_type "other" instead of a known classification |
| INV-5 | Parsers never raise exceptions to callers — errors logged, empty/None returned | Indexers can process large batches without one bad file aborting the run |
| INV-6 | Markdown tags are deduplicated; heading lines are never treated as tags | Prevents duplicate tag entries and false positives from `#` in headings |
| INV-7 | EPUB chapters ordered by OPF spine (canonical reading order) | Chunks appear in the author's intended sequence, not filesystem order |
| INV-8 | Email IDs generated via SHA-256 hash of sender, subject, date if missing | Ensures stable deduplication even when eM Client omits the messageId field |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-1 | `open_ro()` returns `None`, parser yields nothing | Database locked by eM Client or NetNewsWire | Close the app or wait; indexer retries on next run |
| FAIL-2 | `parse_code_file()` returns `None` | Tree-sitter parse failure (corrupted syntax, missing grammar) | Logged and skipped; file excluded from index |
| FAIL-3 | `parse_epub()` returns empty list | EPUB is DRM-protected or not a valid ZIP archive | Book excluded from index; log message indicates possible DRM |
| FAIL-4 | Chunk has section_type "other" | Unknown H2 heading in SPEC.md not in `_SECTION_MAP` | Add heading to `_SECTION_MAP` or use a standard heading |
| FAIL-5 | `parse_markdown()` returns empty frontmatter | Invalid YAML in frontmatter block | Logged as warning; title falls back to filename stem |

## Testing

```bash
uv run pytest tests/test_parsers.py tests/test_code_parser.py tests/test_spec_parser.py tests/test_swift_parser.py -v
```

### Coverage

| Spec Item | Test | Description |
|---|---|---|
| INV-1 | -- | No direct test; `open_ro()` failure path untested |
| INV-2 | -- | No direct test; UTF-8 `errors="replace"` behavior untested |
| INV-3 | `TestSwiftParsing::test_start_end_lines_1_based` | All Swift blocks have 1-based start/end lines |
| INV-3 | `TestSwiftParsing::test_class_line_numbers` | Class declaration has correct 1-based line range |
| INV-3 | `TestZigParsing::test_start_end_lines_1_based` | All Zig blocks have 1-based start/end lines |
| INV-3 | `TestZigParsing::test_pub_prefix_adjusts_start_line` | Pub visibility modifier included in start_line |
| INV-4 | `TestNormalizeSectionType::test_purpose` | "Purpose" heading normalizes to "purpose" |
| INV-4 | `TestNormalizeSectionType::test_core_mechanism` | "Core Mechanism" normalizes to "core_mechanism" |
| INV-4 | `TestNormalizeSectionType::test_case_insensitive` | "INVARIANTS" normalizes to "invariants" |
| INV-4 | `TestNormalizeSectionType::test_extra_whitespace` | Whitespace-padded heading normalizes correctly |
| INV-5 | `TestMinimalInput::test_empty_string` | Empty input returns valid MarkdownDocument, no exception |
| INV-5 | `TestFrontmatter::test_handles_invalid_yaml` | Invalid YAML returns empty frontmatter, no exception |
| INV-6 | `TestTags::test_no_duplicate_tags` | Frontmatter + inline duplicate tag appears only once |
| INV-6 | `TestTags::test_heading_not_treated_as_tag` | `# Heading` not extracted as inline tag |
| INV-6 | `TestTags::test_tag_not_in_code_block` | `#tag` inside code fences ignored |
| INV-7 | -- | No direct test; EPUB spine ordering tested implicitly via `_parse_opf_spine` |
| INV-8 | -- | No direct test; SHA-256 fallback ID generation in `_row_to_email` untested |
| FAIL-2 | -- | No direct test; tree-sitter parse failure on corrupted syntax untested (empty-file tests cover a valid edge case, not the failure mode) |
| FAIL-4 | `TestNormalizeSectionType::test_unknown_heading` | Unknown heading returns "other" section_type |
| FAIL-5 | `TestFrontmatter::test_handles_invalid_yaml` | Invalid YAML returns empty frontmatter dict |

**Gaps:** No automated tests for `open_ro()` failure path (INV-1, FAIL-1), EPUB
parsing (INV-2, INV-7, FAIL-3), email parsing (INV-8), calibre parsing, or RSS
parsing. These parsers interact with external databases and file formats that are
difficult to fixture without integration tests. Additionally, `parse_markdown()`
lacks a top-level try/except — sub-operations (YAML parsing) catch errors, but an
unexpected failure in regex processing or tag extraction could raise to the caller,
which would violate INV-5.

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `ragling.document.chunker` (Chunk, `split_into_windows`, `word_count`) | internal | `src/ragling/document/SPEC.md` -- `spec.py` imports Chunk plus public helpers for window splitting and word counting |
| PyYAML | external | N/A |
| BeautifulSoup (bs4) | external | N/A |
| tree-sitter-language-pack | external | N/A |
