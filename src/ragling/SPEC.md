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

Configuration is frozen and immutable to prevent race conditions across threads.
All writes flow through the IndexingQueue's single worker thread; reads use
separate WAL-mode connections. Leader election via `fcntl.flock()` delegates to
the kernel for automatic cleanup on process death.

**Key files:**
- `config.py` -- frozen Config dataclass and `load_config()`
- `db.py` -- connection management, schema, migrations
- `doc_store.py` -- content-addressed conversion cache
- `embeddings.py` -- Ollama embedding interface
- `indexing_queue.py` -- single-writer job queue
- `indexing_status.py` -- thread-safe progress tracking
- `leader.py` -- per-group leader election via flock
- `sync.py` -- startup discovery and file routing
- `mcp_server.py` -- thin facade: auth setup, `ToolContext` creation, `create_server()`, re-exports for backward compat
- `tools/` -- MCP tool package; each tool in its own module with `register(mcp, ctx)` pattern
- `tools/context.py` -- `ToolContext` dataclass replacing closure captures (group_name, server_config, indexing_status, config_getter, queue_getter, role_getter)
- `tools/helpers.py` -- shared helpers: `_build_source_uri`, `_result_to_dict`, `_get_user_context`, `_convert_document`, etc.
- `tools/{search,batch_search,list_collections,collection_info,index,indexing_status,doc_store_info,search_task,convert}.py` -- one tool per module
- `server.py` -- `ServerOrchestrator` class: startup orchestration (leader election, queue management, config watching, watcher startup, shutdown)
- `cli.py` -- Click CLI commands; `serve` delegates to `ServerOrchestrator`
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
| `LeaderLock`, `lock_path_for_config()` | ServerOrchestrator | `try_acquire()` returns bool; kernel releases on process death |
| `ServerOrchestrator` | CLI (serve) | Startup orchestration; `run()` manages leader election, queue, watchers, shutdown |
| `create_server()` | ServerOrchestrator | Returns configured FastMCP instance |
| `run_startup_sync()`, `submit_file_change()`, `map_file_to_collection()` | ServerOrchestrator, watcher | Daemon thread discovery; file-to-collection routing |
| `apply_forward()`, `apply_reverse()`, `apply_forward_uri()` | MCP server | Longest-prefix path translation between host and container |
| `log_query()` | MCP server | JSONL append with fsync |
| `IndexerType` | IndexingQueue, sync, CLI | StrEnum: PROJECT, CODE, OBSIDIAN, EMAIL, CALIBRE, RSS, PRUNE |

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-1 | Config is a frozen dataclass; mutation raises `FrozenInstanceError` | Shared across threads; mutation would cause race conditions |
| INV-2 | `load_config()` never raises on malformed input; returns default Config | Server must start even with broken config file |
| INV-3 | All SQLite databases use WAL journal mode with retry on first access | Multiple MCP instances read concurrently; WAL avoids reader/writer blocking |
| INV-4 | System collections (email, calibre, RSS) write via the IndexingQueue worker thread. Directory sources (watch collections) use synchronous `sync_directory_source()` from the MCP tool, blocking the caller until complete. | System collections use non-blocking queue; directory sources use blocking walker pipeline for immediate feedback |
| INV-5 | DocStore keys documents by SHA-256 file hash + config_hash; identical content is never converted twice | Avoids redundant Docling conversions that can take minutes per document |
| INV-6 | LeaderLock uses `fcntl.flock()`; kernel releases the lock when the process dies | No stale locks, no PID files, no heartbeat mechanism needed |
| INV-7 | Embedding batch failures fall back to individual embedding with truncation retry | One bad text in a batch must not block the entire batch |
| INV-8 | `load_config()` validates reserved collection names — watch names cannot use names in `RESERVED_COLLECTION_NAMES` (`email`, `calibre`, `rss`, `global`); raises `ValueError` on conflict | Reserved names route to system indexers; user collections with these names would cause routing ambiguity |
| INV-9 | All config paths expanded at load time via `_expand_path()` / `Path.expanduser()` — config object contains only absolute paths | Prevents `~` resolution surprises at use time; all code can assume paths are absolute |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-1 | `OllamaConnectionError` on search or index | Ollama not running or unreachable at configured host | Start Ollama with `ollama serve`; verify `ollama_host` config if using remote |
| FAIL-2 | `OperationalError: database is locked` during WAL setup | Concurrent first-time access to a new database file | Automatic retry with exponential backoff (5 attempts); increase delay if persistent |
| FAIL-3 | IndexingQueue silently drops errors | Indexer raises during `_process()` | Exception logged; status counter decremented; job marked failed in IndexingStatus |
| FAIL-4 | Follower never promoted to leader | Previous leader process died but OS did not release flock | Restart the follower; kernel should release on process death -- if not, check for zombie processes |
| FAIL-5 | Deprecation warnings logged during config loading | Legacy `code_groups` or top-level `obsidian_vaults` keys present in config file | Automatic migration via `migrate_config_dict()`; update config to remove legacy keys to silence warnings |

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
