# Core

## Purpose

The core subsystem provides the foundational runtime for ragling: configuration
loading, database management, document conversion caching, embedding
generation, indexing orchestration, leader election, and the MCP server that
exposes all capabilities as tools.

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

### Document conversion cache

`doc_store.py` implements a content-addressed SQLite cache keyed by SHA-256 file
hash plus a config hash. `get_or_convert()` runs the converter callable before
any DML to avoid holding a write lock during slow conversions. Multiple MCP
instances share the doc store via WAL mode.

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

### CLI

`cli.py` provides the Click command group. The `serve` command implements the full
startup sequence: leader election, IndexingQueue start, startup sync, file watchers,
system watcher, MCP server. Supports stdio, SSE, and dual transport modes.

**Key files:**
- `config.py` -- frozen Config dataclass and `load_config()`
- `db.py` -- connection management, schema, migrations
- `doc_store.py` -- content-addressed conversion cache
- `embeddings.py` -- Ollama embedding interface
- `indexing_queue.py` -- single-writer job queue
- `indexing_status.py` -- thread-safe progress tracking
- `leader.py` -- per-group leader election via flock
- `sync.py` -- startup discovery and file routing
- `mcp_server.py` -- FastMCP tool definitions
- `cli.py` -- Click CLI commands and startup orchestration
- `path_mapping.py` -- host/container path translation
- `query_logger.py` -- JSONL query logging
- `indexer_types.py` -- IndexerType enum

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| `Config`, `load_config()` | All subsystems | Frozen dataclass; `with_overrides()` returns new instance |
| `get_connection()`, `init_db()` | Indexers, search, CLI | Returns sqlite3.Connection with sqlite-vec loaded, WAL mode, busy_timeout set |
| `get_or_create_collection()`, `delete_collection()` | Indexers, IndexingQueue | Collection CRUD; `get_or_create_collection()` returns collection_id, `delete_collection()` removes collection and cascaded rows |
| `DocStore` | Indexers (via IndexingQueue) | Content-addressed cache; `get_or_convert(path, converter, config_hash)` |
| `get_embedding()`, `get_embeddings()`, `serialize_float32()` | Indexers, search | Ollama embedding with retry; binary serialization for sqlite-vec |
| `OllamaConnectionError` | MCP server, CLI | Raised when Ollama is unreachable |
| `IndexingQueue`, `IndexJob` | CLI (serve), sync, watcher | Single-writer queue; `submit()`, `submit_and_wait()`, `shutdown()` |
| `IndexingStatus` | IndexingQueue, MCP server | Thread-safe progress; `to_dict()` returns status or None when idle |
| `LeaderLock`, `lock_path_for_config()` | CLI (serve) | `try_acquire()` returns bool; kernel releases on process death |
| `create_server()` | CLI (serve) | Returns configured FastMCP instance |
| `run_startup_sync()`, `submit_file_change()`, `map_file_to_collection()` | CLI (serve), watcher | Daemon thread discovery; file-to-collection routing |
| `apply_forward()`, `apply_reverse()`, `apply_forward_uri()` | MCP server | Longest-prefix path translation between host and container |
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
| INV-8 | LeaderLock uses `fcntl.flock()`; kernel releases the lock when the process dies | No stale locks, no PID files, no heartbeat mechanism needed |
| INV-9 | Embedding batch failures fall back to individual embedding with truncation retry | One bad text in a batch must not block the entire batch |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-1 | `OllamaConnectionError` on search or index | Ollama not running or unreachable at configured host | Start Ollama with `ollama serve`; verify `ollama_host` config if using remote |
| FAIL-2 | `OperationalError: database is locked` during WAL setup | Concurrent first-time access to a new database file | Automatic retry with exponential backoff (5 attempts); increase delay if persistent |
| FAIL-4 | IndexingQueue silently drops errors | Indexer raises during `_process()` | Exception logged; status counter decremented; job marked failed in IndexingStatus |
| FAIL-5 | Follower never promoted to leader | Previous leader process died but OS did not release flock | Restart the follower; kernel should release on process death -- if not, check for zombie processes |

## Testing

```bash
uv run pytest tests/test_config.py tests/test_db.py tests/test_doc_store.py \
  tests/test_embeddings.py tests/test_indexing_queue.py \
  tests/test_indexing_status.py tests/test_leader.py tests/test_sync.py \
  tests/test_path_mapping.py -v
```

### Coverage

| Spec Item | Test | Description |
|---|---|---|
| INV-1 | `test_config.py::TestConfigImmutability::test_config_is_frozen` | Asserts `FrozenInstanceError` on direct attribute assignment |
| INV-1 | `test_config.py::TestConfigImmutability::test_with_overrides_returns_new_instance` | Verifies `with_overrides()` returns a new Config, original unchanged |
| INV-2 | `test_config.py::TestMalformedConfigFallback::test_malformed_json_falls_back_to_defaults` | Verifies default Config returned for malformed JSON |
| INV-3 | `test_db.py::TestGetConnection::test_wal_mode_enabled` | Checks `PRAGMA journal_mode` returns `wal` |
| INV-4 | `test_indexing_queue.py::TestSingleWriterDesign::test_indexer_runs_on_worker_thread` | Captures thread name during processing, asserts it is `index-worker` |
| INV-5 | `test_doc_store.py::TestGetOrConvert::test_cache_hit_skips_converter` | Verifies converter not called on second access with same hash |
| INV-5 | `test_doc_store.py::TestConfigHashCaching::test_different_config_hash_triggers_reconversion` | Different config_hash triggers reconversion |
| INV-8 | `test_leader.py::TestLeaderLock::test_second_lock_on_same_path_fails` | Second lock on same file fails to acquire |
| INV-8 | `test_leader.py::TestLeaderLock::test_release_allows_reacquisition` | After close(), another process can acquire |
| INV-9 | `test_embeddings.py::TestGetEmbeddingTruncationRetry::test_failure_retries_with_truncated_text` | Verifies retry with truncated text on first failure |
| INV-9 | `test_embeddings.py::TestGetEmbeddingsBatchFallback::test_batch_failure_retries_individually` | Batch failure falls back to per-text embedding |
| FAIL-1 | `test_embeddings.py::TestHostAwareErrorMessages::test_default_message_suggests_ollama_serve` | Verifies `OllamaConnectionError` raised with helpful message |
| FAIL-2 | `test_db.py::TestGetConnection::test_wal_mode_enabled` | WAL retry logic exercised on connection setup |
| FAIL-4 | `test_indexing_queue.py::TestIndexingQueue::test_worker_handles_exceptions` | Error in one job does not stop the worker |
| FAIL-5 | `test_leader.py::TestLeaderLockRetry::test_retry_promotes_after_leader_releases` | Follower promoted after leader releases lock |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| Document | internal | `src/ragling/document/SPEC.md` -- document conversion, chunking, format bridging |
| Auth | internal | `src/ragling/auth/SPEC.md` -- API key resolution, TLS, token verification |
| Search | internal | `src/ragling/search/SPEC.md` -- hybrid search with RRF |
| Watchers | internal | `src/ragling/watchers/SPEC.md` -- filesystem, database, config change monitoring |
| Indexers | internal (circular) | `src/ragling/indexers/SPEC.md` -- Core dispatches to indexers via IndexingQueue; indexers depend on Core utilities. Mutual dependency by design. |
| sqlite-vec | external | N/A -- SQLite extension for vector similarity search |
| Ollama | external | N/A -- local LLM/embedding server |
| FastMCP | external | N/A -- MCP server framework |
| Click | external | N/A -- CLI framework |
