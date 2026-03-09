# Indexers

## Purpose

Source-specific indexing pipelines that discover content, detect changes,
parse via the parsers subsystem, chunk and embed text, and persist results
to the per-group SQLite database. Every indexer extends `BaseIndexer` ABC
and implements the `index()` method.

The key design decision: two-pass indexing (scan for changes, then index
changed sources) combined with three change-detection strategies -- file
hash, watermark timestamp, and HEAD SHA comparison -- to keep incremental
re-indexing fast across heterogeneous source types.

## Core Mechanism

Two-pass indexing (scan for changes, then index changed sources) with three
change-detection strategies: file hash, watermark timestamp, and HEAD SHA
comparison. The unified DFS walker (`walker.py`) traverses directory trees,
routing each file to exactly one parser. `walk_processor.py` handles the
parse/embed/persist pipeline for walker results.

**Key files:**
- `base.py` -- `BaseIndexer` ABC, `upsert_source_with_chunks()`,
  `delete_source()`, `prune_stale_sources()`, `IndexResult`, `file_hash()`
- `auto_indexer.py` -- `detect_directory_type()`,
  `detect_indexer_type_for_file()`, `collect_indexable_directories()`
- `walker.py` -- unified DFS walker: `walk()`, `route_file()`, `FileRoute`,
  `WalkResult`, `WalkStats`, `ExclusionConfig`, `assign_collection()`,
  `format_plan()`
- `walk_processor.py` -- `process_walk_result()`: parse, embed, persist pipeline
- `obsidian.py` -- `ObsidianIndexer` for Obsidian vault files
- `email_indexer.py` -- `EmailIndexer` for eM Client emails
- `calibre_indexer.py` -- `CalibreIndexer` for Calibre ebooks
- `git_commands.py` -- pure git subprocess helpers: `run_git()`,
  `is_git_repo()`, `get_head_sha()`, `git_ls_files()`, `CommitInfo`,
  `FileChange`, and commit history/diff extraction functions
- `git_indexer.py` -- `GitRepoIndexer` for code repos (tree-sitter +
  commit history); delegates git CLI operations to `git_commands.py`
- `rss_indexer.py` -- `RSSIndexer` for NetNewsWire RSS articles
- `factory.py` -- `create_indexer()` centralized indexer creation; single
  source of truth for mapping collection names/types to indexer instances
- `format_routing.py` -- `EXTENSION_MAP`, `SUPPORTED_EXTENSIONS`,
  `is_supported_extension()`, `parse_and_chunk()` shared format dispatch
- `project.py` -- `ProjectIndexer` with auto-discovery and delegation;
  re-exports `_EXTENSION_MAP`, `_SUPPORTED_EXTENSIONS` for backward compat

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| `create_indexer()` | `indexing_queue.py`, `cli.py` | Factory function: maps collection name/IndexerType to configured indexer instance |
| `BaseIndexer` ABC | All indexers | Must implement `index(conn, config, force, status) -> IndexResult` |
| `upsert_source_with_chunks()` | All indexers | Atomic delete-then-insert of source + documents + vectors; commits transaction |
| `delete_source()` | `GitRepoIndexer`, `prune_stale_sources()` | Removes source row and cascaded documents/vectors; no-op if source absent |
| `prune_stale_sources()` | `ObsidianIndexer`, `CalibreIndexer`, `ProjectIndexer` | Removes file-backed sources whose files no longer exist; skips virtual URIs |
| `file_hash()` | All file-based indexers | Returns SHA-256 hex digest of file contents |
| `IndexResult` | All indexers, `indexing_queue.py` | Dataclass tracking indexed/skipped/skipped_empty/pruned/errors/total_found counts plus `error_messages: list[str]` |
| `detect_directory_type()` | `ProjectIndexer`, sync module | Returns `IndexerType.OBSIDIAN`, `CODE`, or `PROJECT` based on marker files |
| `detect_indexer_type_for_file()` | Sync module | Walks parent directories for `.obsidian`/`.git` markers; returns `IndexerType` |
| `collect_indexable_directories()` | Sync module | Filters configured usernames against existing subdirectories |
| `walk()` | `sync.py`, `tools/index.py` | DFS traversal returning `WalkResult` with routing decisions |
| `process_walk_result()` | `sync.py`, `tools/index.py` | Parse/embed/persist pipeline for walker output |
| `route_file()` | `walk()` internal, tests | Routes a single file to its parser type |
| `assign_collection()` | `walk_processor.py`, `format_plan()` | Maps file context to collection name |
| `ObsidianIndexer` | `indexing_queue.py`, `ProjectIndexer` | Indexes all supported file types in Obsidian vaults |
| `EmailIndexer` | `indexing_queue.py` | Indexes emails from eM Client with watermark-based incrementality |
| `CalibreIndexer` | `indexing_queue.py` | Indexes ebooks from Calibre libraries with rich metadata enrichment |
| `GitRepoIndexer` | `indexing_queue.py`, `ProjectIndexer` | Indexes code files (tree-sitter) and optionally commit history |
| `RSSIndexer` | `indexing_queue.py` | Indexes RSS articles from NetNewsWire with watermark-based incrementality |
| `ProjectIndexer` | `indexing_queue.py` | Auto-discovers vaults/repos, delegates to specialized indexers, indexes leftovers |
| `EXTENSION_MAP` | `format_routing.py`, `project.py`, `obsidian.py` | Maps file extensions to source types; canonical definition in `format_routing.py` |
| `SUPPORTED_EXTENSIONS` | `format_routing.py` | Frozenset of all indexable file extensions (document + code) |
| `is_supported_extension()` | `format_routing.py`, re-exported by `project.py` | Checks if a file extension is supported for indexing |
| `parse_and_chunk()` | `format_routing.py`, `project.py`, `obsidian.py` | Routes files to the correct parser/chunker pipeline by source type |
| `_SUPPORTED_EXTENSIONS` | Core (`watcher.py`) | Backward-compat re-export from `project.py`; delegates to `format_routing.SUPPORTED_EXTENSIONS` |

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-1 | `upsert_source_with_chunks()` is atomic: delete old documents/vectors, insert new ones, commit in one transaction | Partial writes leave the index in an inconsistent state with orphan vectors or missing documents |
| INV-2 | Every source maps to 1+ documents; every document maps to exactly 1 embedding vector | Search relies on joining sources -> documents -> vec_documents; broken chains produce phantom or missing results |
| INV-3 | File-backed sources use SHA-256 content hash for change detection; virtual sources (email, RSS, commits) use source_path + watermark | Mixing strategies causes either missed updates or unnecessary re-indexing |
| INV-4 | Git repo watermarks stored as JSON dict in `collections.description` (system of record). Email/RSS watermarks computed from `MAX(json_extract(d.metadata, '$.date'))` in documents table; `collections.description` updated with human-readable tracking string as side effect | Watermark loss triggers full re-index; corruption must fall back gracefully |
| INV-5 | `prune_stale_sources()` only removes file-backed sources whose files no longer exist; skips virtual URIs (non-`/` prefix) and sources without file_hash | Pruning virtual sources (email, RSS, calibre descriptions) would permanently delete valid data |
| INV-6 | The unified walker routes each file to exactly one parser (spec > docling > markdown > treesitter > plaintext > skip) | Duplicate or conflicting parsing wastes resources and produces inconsistent chunks |
| INV-7 | Obsidian indexer skips hidden dirs, `.obsidian`, `.trash`, `.git`, and user-excluded folders | Indexing system/config files pollutes search results with non-content data |
| INV-8 | Database lock retry: 3 attempts with 2s delay for eM Client and NetNewsWire databases | External apps hold locks during normal operation; immediate failure would prevent indexing |
| INV-9 | Per-item errors do not cascade: logged, counted in `IndexResult`, execution continues | One corrupt file or email must not abort the entire indexing run |
| INV-10 | Git indexer routes SPEC.md files to the dedicated spec parser for section-level chunking | SPEC.md files require structural parsing by section, not tree-sitter code parsing |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-1 | Indexing returns errors for email/RSS, no new content indexed | External database locked by eM Client or NetNewsWire | Retry 3x with 2s backoff; `IndexResult` records error after exhaustion; close the external app and retry |
| FAIL-2 | Warning logged, file skipped, error count incremented | File deleted between scan pass and index pass | No action needed; next run will prune the stale source via `prune_stale_sources()` |
| FAIL-3 | Orphaned sub-collections persist after directory restructure | Vault or repo marker removed from a project directory | `reconcile_sub_collections()` deletes sub-collections not in current discovery |
| FAIL-4 | `OllamaConnectionError` propagated, `IndexResult` records error | Ollama embedding API timeout or unavailable | Ensure Ollama is running and the configured model is pulled |
| FAIL-5 | Full re-index triggered unexpectedly | Watermark corruption (invalid JSON, unparseable date) | Parser falls back to empty watermarks, triggering full re-index; manual fix by clearing collection description |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| Parsers (markdown, epub, code, email, rss, calibre, spec) | internal | `src/ragling/parsers/SPEC.md` |
| `db.py` (get_or_create_collection, delete_collection) | internal | `src/ragling/SPEC.md` |
| `embeddings.py` (get_embeddings, serialize_float32) | internal | `src/ragling/SPEC.md` |
| `ragling.document` (Chunk, convert_and_chunk, chunk_with_hybrid, bridges) | internal | `src/ragling/document/SPEC.md` |
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| `doc_store.py` (DocStore) | internal | `src/ragling/SPEC.md` |
| `indexing_status.py` (IndexingStatus) | internal | `src/ragling/SPEC.md` |
| `indexer_types.py` (IndexerType) | internal | `src/ragling/SPEC.md` |
| Ollama (embedding API) | external | N/A |
| tree-sitter (code parsing) | external | N/A |
| git CLI | external | N/A |
