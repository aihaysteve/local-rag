# Core

## Purpose

The core subsystem provides the foundational runtime for ragling: configuration
loading, database management, hybrid search, document conversion caching,
embedding generation, indexing orchestration, file watching, leader election,
authentication, and the MCP server that exposes all capabilities as tools.

The key design decision is single-writer architecture: all database writes flow
through one IndexingQueue worker thread per group, eliminating write contention
by design. Reads (search, listing) happen on separate connections using WAL mode
for concurrent access across multiple MCP instances.

## Core Mechanism

### Configuration

`config.py` defines Config as a frozen dataclass with `with_overrides()` for
deriving variants. Immutability is enforced via `MappingProxyType` for dicts,
tuples for lists, and `frozenset` for sets. `load_config()` reads JSON from
`~/.ragling/config.json`, falling back to defaults on malformed input.

### Database

`db.py` manages per-group SQLite index databases. `get_connection()` loads the
sqlite-vec extension, sets WAL mode with retry (5 attempts, exponential backoff
from 50ms), `busy_timeout=5000`, and `foreign_keys=ON`. `init_db()` creates the
full schema: `collections`, `sources`, `documents` tables; `vec_documents`
(sqlite-vec) and `documents_fts` (FTS5) virtual tables; and FTS sync triggers.
`SCHEMA_VERSION=2` with forward migration support.

### Search

`search.py` implements hybrid search via Reciprocal Rank Fusion. `_vector_search()`
queries sqlite-vec by embedding distance; `_fts_search()` queries FTS5 by keyword
match. `rrf_merge()` combines the two ranked lists with configurable weights
(default: vector 0.7, FTS 0.3, k=60). `_mark_stale_results()` compares file mtime
to indexed timestamp, marking results whose source files have changed or been
deleted. `search_utils.py` provides `escape_fts_query()` for safe FTS5 input.

### Document conversion cache

`doc_store.py` implements a content-addressed SQLite cache keyed by SHA-256 file
hash plus a config hash. `get_or_convert()` runs the converter callable before
any DML to avoid holding a write lock during slow conversions. Multiple MCP
instances share the doc store via WAL mode.

### Chunking

`chunker.py` defines the Chunk dataclass (text, title, metadata, chunk_index) and
`_split_into_windows()` for word-based overlapping window splitting.

### Embeddings

`embeddings.py` interfaces with Ollama. Texts are sent in sub-batches of 32 with a
300-second timeout. On batch failure, falls back to individual embedding with
truncation retry (256 words). `serialize_float32()` converts vectors to sqlite-vec
binary format.

### Indexing orchestration

`indexing_queue.py` provides the single-writer queue. `IndexJob` (frozen dataclass)
describes a unit of work; `IndexRequest` wraps it with a `threading.Event` for
synchronous submission. The worker thread routes jobs to the correct indexer via a
dispatch dict. `indexing_status.py` tracks progress per-collection with thread-safe
counters (job-level, file-level, byte-level, failure tracking).

### Leader election

`leader.py` implements per-group leader election using `fcntl.flock()`. The kernel
releases the lock when the process dies, so there are no stale locks, no PID files,
and no heartbeats. Followers retry periodically via `start_retry()` with a
configurable interval and promotion callback.

### File watching

`watcher.py` uses watchdog to monitor configured directories with a 2-second
debounced queue. `_Handler` filters by file extension and hidden directories, and
passes through git state files (`.git/HEAD`, `.git/refs/`). `system_watcher.py`
monitors external SQLite databases (email, calibre, RSS) with a 10-second debounce.
`config_watcher.py` watches the config file with a 2-second debounce, preserving
the old config on parse errors.

### Startup sync

`sync.py` spawns a daemon thread that discovers all configured sources (home dirs,
global paths, obsidian vaults, code groups, watch dirs, system collections) and
submits `IndexJob` items. `submit_file_change()` routes file changes to the
correct collection and indexer type.

### MCP server

`mcp_server.py` builds a FastMCP server with tools: `rag_search`,
`rag_batch_search`, `rag_list_collections`, `rag_index`, `rag_indexing_status`,
`rag_doc_store_info`, `rag_collection_info`, `rag_convert`. Auth via
`RaglingTokenVerifier` when users are configured.

### Authentication and transport

`auth.py` resolves API keys to `UserContext` using `hmac.compare_digest` for
timing-safe comparison. `token_verifier.py` implements rate limiting with
exponential backoff (max 5 failures, max 300s backoff, cleanup every 10 minutes).
`tls.py` generates self-signed ECDSA P-256 certificates (CA ~10 years, server cert
1 year) with auto-renewal. `path_mapping.py` translates paths between host and
container (longest prefix match).

### Document conversion and chunking

`docling_convert.py` wraps Docling's `DocumentConverter` for format conversion
(PDF, DOCX, PPTX, XLSX, HTML, images, audio) and `HybridChunker` for
structure-aware chunking. `get_converter()` is an `lru_cache` singleton
configured per enrichment settings. `convert_and_chunk()` integrates with DocStore
for content-addressed caching, with fallbacks for PDF (pypdfium2 text extraction)
and standalone images (VLM description via SmolVLM or Ollama).
`converter_config_hash()` produces a deterministic hash of pipeline settings so
changing enrichments invalidates cached conversions.

`docling_bridge.py` converts legacy parser output (markdown, epub, plaintext,
email, RSS) into `DoclingDocument` objects so all formats can be chunked by
`HybridChunker` with `contextualize()`. Each bridge function
(`markdown_to_docling_doc`, `epub_to_docling_doc`, etc.) preserves heading
hierarchy and paragraph structure.

### CLI

`cli.py` provides the Click command group. The `serve` command implements the full
startup sequence: leader election, IndexingQueue start, startup sync, file watchers,
system watcher, MCP server. Supports stdio, SSE, and dual transport modes.

**Key files:**
- `config.py` — frozen Config dataclass and `load_config()`
- `db.py` — connection management, schema, migrations
- `search.py` — hybrid vector + FTS search with RRF
- `doc_store.py` — content-addressed conversion cache
- `embeddings.py` — Ollama embedding interface
- `chunker.py` — Chunk dataclass and window splitting
- `indexing_queue.py` — single-writer job queue
- `indexing_status.py` — thread-safe progress tracking
- `leader.py` — per-group leader election via flock
- `sync.py` — startup discovery and file routing
- `mcp_server.py` — FastMCP tool definitions
- `cli.py` — Click CLI commands and startup orchestration
- `auth.py` — API key resolution and user context
- `token_verifier.py` — rate-limited token verification
- `tls.py` — self-signed certificate generation
- `watcher.py` — filesystem change monitoring
- `system_watcher.py` — external database monitoring
- `config_watcher.py` — config file reload
- `path_mapping.py` — host/container path translation
- `docling_convert.py` — Docling conversion, HybridChunker, VLM fallbacks
- `docling_bridge.py` — legacy parser output to DoclingDocument bridge
- `search_utils.py` — FTS query escaping
- `query_logger.py` — JSONL query logging
- `indexer_types.py` — IndexerType enum

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| `Config`, `load_config()` | All subsystems | Frozen dataclass; `with_overrides()` returns new instance |
| `get_connection()`, `init_db()` | Indexers, search, CLI | Returns sqlite3.Connection with sqlite-vec loaded, WAL mode, busy_timeout set |
| `search()`, `perform_search()`, `perform_batch_search()` | MCP server, CLI | Returns `list[SearchResult]` with RRF-merged hybrid results |
| `SearchResult`, `SearchFilters`, `BatchQuery` | MCP server | Dataclasses for search input/output |
| `rrf_merge()` | Tests | Merges two ranked lists by Reciprocal Rank Fusion |
| `DocStore` | Indexers (via IndexingQueue) | Content-addressed cache; `get_or_convert(path, converter, config_hash)` |
| `get_embedding()`, `get_embeddings()`, `serialize_float32()` | Indexers, search | Ollama embedding with retry; binary serialization for sqlite-vec |
| `OllamaConnectionError` | MCP server, CLI | Raised when Ollama is unreachable |
| `Chunk` | Indexers, parsers | Dataclass with text, title, metadata, chunk_index |
| `convert_and_chunk()` | Indexers (Obsidian, Project, Calibre) | Docling conversion with DocStore caching + HybridChunker; returns `list[Chunk]` |
| `chunk_with_hybrid()` | Indexers, `convert_and_chunk()` | Chunks a DoclingDocument via HybridChunker with `contextualize()`; returns `list[Chunk]` |
| `converter_config_hash()` | Indexers | Deterministic hash of pipeline settings for DocStore cache keying |
| `markdown_to_docling_doc()`, `epub_to_docling_doc()`, `plaintext_to_docling_doc()` | Indexers (Obsidian, Project) | Bridge functions converting legacy parser output to DoclingDocument |
| `email_to_docling_doc()`, `rss_to_docling_doc()` | Indexers (Email, RSS) | Bridge functions for email and RSS content to DoclingDocument |
| `IndexingQueue`, `IndexJob` | CLI (serve), sync, watcher | Single-writer queue; `submit()`, `submit_and_wait()`, `shutdown()` |
| `IndexingStatus` | IndexingQueue, MCP server | Thread-safe progress; `to_dict()` returns status or None when idle |
| `LeaderLock`, `lock_path_for_config()` | CLI (serve) | `try_acquire()` returns bool; kernel releases on process death |
| `create_server()` | CLI (serve) | Returns configured FastMCP instance |
| `run_startup_sync()`, `submit_file_change()`, `map_file_to_collection()` | CLI (serve), watcher | Daemon thread discovery; file-to-collection routing |
| `start_watcher()`, `get_watch_paths()` | CLI (serve) | Returns watchdog Observer monitoring configured paths |
| `start_system_watcher()` | CLI (serve) | Returns SystemCollectionWatcher for external DB monitoring |
| `ConfigWatcher` | CLI (serve) | Debounced config reload with `get_config()` |
| `resolve_api_key()`, `UserContext` | MCP server | Timing-safe key lookup; `visible_collections()` computes access |
| `RaglingTokenVerifier` | MCP server | Rate-limited token verification with exponential backoff |
| `ensure_tls_certs()` | CLI (serve) | Returns (cert_path, key_path, ca_path); auto-renews on expiry |
| `apply_forward()`, `apply_reverse()`, `apply_forward_uri()` | MCP server | Longest-prefix path translation between host and container |
| `escape_fts_query()` | search.py | Wraps query in quotes, doubles internal quotes per FTS5 spec |
| `log_query()` | MCP server | JSONL append with fsync |
| `IndexerType` | IndexingQueue, sync, CLI | StrEnum: PROJECT, CODE, OBSIDIAN, EMAIL, CALIBRE, RSS, PRUNE |

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-1 | Config is a frozen dataclass; mutation raises `FrozenInstanceError` | Shared across threads; mutation would cause race conditions |
| INV-2 | `load_config()` never raises on malformed input; returns default Config | Server must start even with broken config file |
| INV-3 | All SQLite databases use WAL journal mode with retry on first access | Multiple MCP instances read concurrently; WAL avoids reader/writer blocking |
| INV-4 | Only the IndexingQueue worker thread writes to the per-group index database | Eliminates write contention; no locking needed in indexers |
| INV-5 | DocStore keys documents by SHA-256 file hash + config_hash; identical content is never converted twice | Avoids redundant Docling conversions that can take minutes per document |
| INV-6 | `rrf_merge()` produces scores that decrease monotonically when iterated in order | Callers rely on results being sorted by relevance |
| INV-7 | `resolve_api_key()` uses `hmac.compare_digest` for all key comparisons | Prevents timing side-channel attacks on API keys |
| INV-8 | LeaderLock uses `fcntl.flock()`; kernel releases the lock when the process dies | No stale locks, no PID files, no heartbeat mechanism needed |
| INV-9 | Embedding batch failures fall back to individual embedding with truncation retry | One bad text in a batch must not block the entire batch |
| INV-10 | `_Handler` filters events by file extension (case-insensitive) and skips hidden directories (except `.git/HEAD` and `.git/refs/`) | Prevents indexing binary files, editor temps, and noisy dotfile churn |
| INV-11 | `get_watch_paths()` deduplicates paths that appear in multiple config sources | Prevents duplicate watchdog observers on the same directory |
| INV-12 | Token verifier rate-limits failed auth attempts with exponential backoff capped at 300 seconds | Prevents brute-force API key guessing without permanently locking out users |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-1 | `OllamaConnectionError` on search or index | Ollama not running or unreachable at configured host | Start Ollama with `ollama serve`; verify `ollama_host` config if using remote |
| FAIL-2 | `OperationalError: database is locked` during WAL setup | Concurrent first-time access to a new database file | Automatic retry with exponential backoff (5 attempts); increase delay if persistent |
| FAIL-3 | Search returns stale results marked `stale=True` | Source file modified or deleted after indexing | Re-index the affected collection; stale marking is informational |
| FAIL-4 | IndexingQueue silently drops errors | Indexer raises during `_process()` | Exception logged; status counter decremented; job marked failed in IndexingStatus |
| FAIL-5 | Follower never promoted to leader | Previous leader process died but OS did not release flock | Restart the follower; kernel should release on process death — if not, check for zombie processes |
| FAIL-6 | Config reload ignored after file change | ConfigWatcher debounce timer not expired; or parse error in new config | Check logs for parse errors; old config preserved on error |
| FAIL-7 | Rate limiter blocks legitimate user after failed attempts | Exceeds MAX_FAILURES (5) threshold with wrong key | Wait for backoff to expire (max 300s); or restart the server to clear rate-limit state |

## Testing

```bash
uv run pytest tests/test_config.py tests/test_db.py tests/test_search.py \
  tests/test_doc_store.py tests/test_embeddings.py tests/test_chunker.py \
  tests/test_indexing_queue.py tests/test_indexing_status.py tests/test_leader.py \
  tests/test_sync.py tests/test_watcher.py tests/test_auth.py tests/test_tls.py \
  tests/test_token_verifier.py tests/test_search_utils.py tests/test_path_mapping.py \
  tests/test_system_watcher.py tests/test_config_watcher.py -v
```

### Coverage

| Spec Item | Test | Description |
|---|---|---|
| INV-1 | `test_config.py::TestFrozenConfig::test_config_is_immutable` | Asserts `FrozenInstanceError` on direct attribute assignment |
| INV-1 | `test_config.py::TestFrozenConfig::test_with_overrides_returns_new_instance` | Verifies `with_overrides()` returns a new Config, original unchanged |
| INV-2 | `test_config.py::TestLoadConfig::test_malformed_json_returns_default` | Verifies default Config returned for malformed JSON |
| INV-3 | `test_db.py::TestGetConnection::test_wal_mode_enabled` | Checks `PRAGMA journal_mode` returns `wal` |
| INV-4 | `test_indexing_queue.py::TestSingleWriterDesign::test_worker_thread_is_the_only_writer` | Captures thread name during processing, asserts it is `index-worker` |
| INV-5 | `test_doc_store.py::TestDocStore::test_cache_hit_returns_cached` | Verifies converter not called on second access with same hash |
| INV-5 | `test_doc_store.py::TestDocStore::test_config_hash_produces_separate_cache_entries` | Different config_hash triggers reconversion |
| INV-6 | `test_search.py::TestRRFMerge::test_rrf_scores_monotonically_decrease` | Asserts each score is >= the next in merged output |
| INV-7 | `test_auth.py::TestResolveApiKey::test_timing_safe_comparison` | Verifies `hmac.compare_digest` is called (mocked) |
| INV-8 | `test_leader.py::TestLeaderLock::test_acquire_and_contention` | Second lock on same file fails to acquire |
| INV-8 | `test_leader.py::TestLeaderLock::test_release_allows_reacquire` | After close(), another process can acquire |
| INV-9 | `test_embeddings.py::TestGetEmbedding::test_truncation_retry_on_failure` | Verifies retry with truncated text on first failure |
| INV-9 | `test_embeddings.py::TestGetEmbeddings::test_batch_fallback_to_individual` | Batch failure falls back to per-text embedding |
| INV-10 | `test_watcher.py::TestHandlerExtensionFiltering::test_unsupported_extension_ignored_on_modified` | Unsupported extension does not enqueue |
| INV-10 | `test_watcher.py::TestHandlerExtensionFiltering::test_filtering_is_case_insensitive` | Uppercase extension still matches |
| INV-10 | `test_watcher.py::TestHandlerHiddenDirectoryFiltering::test_file_in_hidden_directory_not_enqueued` | Files in dotdirs skipped |
| INV-10 | `test_watcher.py::TestHandlerGitStateFiles::test_git_head_change_is_enqueued` | `.git/HEAD` changes pass through |
| INV-10 | `test_watcher.py::TestHandlerGitStateFiles::test_git_objects_change_is_not_enqueued` | `.git/objects/` changes filtered out |
| INV-11 | `test_watcher.py::TestWatchPathsIncludesObsidianAndCode::test_deduplicates_overlapping_paths` | Same path in home and obsidian appears once |
| INV-12 | `test_token_verifier.py::TestRaglingTokenVerifier::test_rate_limiting_after_failures` | Rejects immediately after MAX_FAILURES exceeded |
| INV-12 | `test_token_verifier.py::TestRaglingTokenVerifier::test_backoff_increases_exponentially` | Backoff time doubles per failure |
| FAIL-1 | `test_embeddings.py::TestGetEmbedding::test_connection_refused_error_message` | Verifies `OllamaConnectionError` raised with helpful message |
| FAIL-2 | `test_db.py::TestGetConnection::test_wal_mode_enabled` | WAL retry logic exercised on connection setup |
| FAIL-3 | `test_search.py::TestStaleResults::test_stale_when_file_deleted` | Deleted source file marked stale |
| FAIL-3 | `test_search.py::TestStaleResults::test_stale_when_file_modified` | Modified source file marked stale |
| FAIL-4 | `test_indexing_queue.py::TestIndexingQueue::test_worker_continues_after_error` | Error in one job does not stop the worker |
| FAIL-5 | `test_leader.py::TestLeaderLock::test_retry_promotes_after_release` | Follower promoted after leader releases lock |
| FAIL-6 | `test_config_watcher.py::TestConfigWatcher::test_debounce_batches_rapid_changes` | Rapid changes batched within debounce window |
| FAIL-7 | `test_token_verifier.py::TestRaglingTokenVerifier::test_rate_limiting_after_failures` | Rate limiter blocks after threshold exceeded |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| Indexers | internal | `src/ragling/indexers/SPEC.md` |
| sqlite-vec | external | N/A — SQLite extension for vector similarity search |
| Ollama | external | N/A — local LLM/embedding server |
| FastMCP | external | N/A — MCP server framework |
| watchdog | external | N/A — filesystem event monitoring |
| Docling | external | N/A — document conversion (PDF, DOCX, etc.) |
| Click | external | N/A — CLI framework |
