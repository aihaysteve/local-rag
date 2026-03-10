# Ragling Design

Design patterns, conventions, and rationale for the ragling codebase.
For system structure, schemas, and data flow, see [Architecture](architecture.md).

---

## Design Philosophy

Two principles shape every design decision:

**Everything runs locally.** No cloud APIs, no API keys, no data leaves the
machine. Embeddings run through a local Ollama instance (bge-m3 by default,
1024 dimensions). Document conversion uses Docling's local pipelines
including SmolVLM for image descriptions. Full-text search uses SQLite FTS5,
vector search uses sqlite-vec. This eliminates privacy concerns and network
dependencies but requires careful resource management -- all compute happens
on the user's hardware.

**Content-addressed caching.** Docling conversions are cached in a shared
SQLite store keyed by SHA-256 file hash plus converter config hash. Multiple
MCP instances share this cache via WAL mode, so a document is never
converted twice. The `DocStore` class in `src/ragling/doc_store.py`
implements the `get_or_convert()` pattern: on cache hit (matching
`content_hash` and `config_hash`) the stored JSON is returned directly; on
miss the supplied converter callable is invoked, stale conversions are
removed, and the new result is stored and returned.

Changing enrichment settings (e.g., enabling table extraction or switching
VLM backends) automatically invalidates the cache because
`converter_config_hash()` in `src/ragling/document/docling_convert.py`
produces a different 16-character hex digest from the SHA-256 of the
JSON-serialized pipeline settings. This makes incremental re-indexing fast:
only new or changed files trigger expensive Docling conversions.

---

## Chunking Strategy

Ragling uses Docling's `HybridChunker` as its primary chunking strategy
because it preserves document structure. Unlike naive text splitting,
`HybridChunker` keeps headings, tables, code blocks, and list items intact
as atomic units, splitting only when a structural element exceeds the token
budget. The default chunk size is 256 tokens with 50 tokens of overlap,
aligned to the bge-m3 tokenizer via a `HuggingFaceTokenizer` wrapper.

The tokenizer is created by `_get_tokenizer()` in
`src/ragling/document/docling_convert.py`, which is `@lru_cache`-decorated
to avoid re-instantiating the `AutoTokenizer` on every call.

The `contextualize()` method on each chunk prepends the heading hierarchy
as a context prefix, so a chunk deep in a nested section carries its full
heading path. This is critical for retrieval quality: a chunk about
"Installation" under "macOS" under "Getting Started" gets the full
breadcrumb, making it distinguishable from an "Installation" chunk in
a different context.

Enrichment metadata -- picture descriptions from VLM inference, table
captions from TableFormer, code language tags from code enrichment -- is
extracted from Docling's `doc_items` (`PictureItem`, `TableItem`, `CodeItem`
types) and stored in the chunk's metadata dict, persisted as JSON in the
documents table.

For parsers that produce raw text rather than Docling documents, the
`split_into_windows()` function in `src/ragling/document/chunker.py`
provides a simpler fallback. It splits text into overlapping word-based
windows, advancing by `chunk_size - overlap` words per step. This is
intentionally unsophisticated -- it exists only for content types where
structural chunking is not applicable.

Key files: `src/ragling/document/chunker.py`,
`src/ragling/document/docling_convert.py`.

---

## Authentication and Visibility

Ragling supports two transports with different authentication models. The
stdio transport, used when the MCP server is launched by a local IDE or CLI,
requires no authentication and grants full access to all collections. The
SSE transport, used for remote or multi-user access over HTTPS, requires
Bearer token authentication with TLS.

The SSE auth flow starts with a Bearer token in the Authorization header.
`RaglingTokenVerifier.verify_token()` in
`src/ragling/auth/token_verifier.py` receives the token and delegates to
`resolve_api_key()` in `src/ragling/auth/auth.py`. The resolution iterates
over all configured users and uses `hmac.compare_digest()` for timing-safe
comparison against each stored `api_key`. This constant-time comparison
prevents side-channel attacks that could leak key prefixes through response
timing. On success, a `UserContext` dataclass is returned containing the
`username`, `system_collections` list, and `path_mappings` dict.

Visibility rules determine which collections a user can search. An
authenticated user sees their own collection (named after their username),
plus the `global` collection if configured, plus any collections listed in
their `system_collections` field (e.g., `["email", "calibre"]`). Stdio
connections bypass visibility entirely and see all collections. The
`visible_collections()` method on `UserContext` computes this list.

Rate limiting protects against brute-force API key guessing.
`RaglingTokenVerifier` tracks failed attempts per hashed token with
exponential backoff: after `MAX_FAILURES=5` failures, subsequent attempts
are rejected with `RateLimitedError` and a backoff of
`min(2^count, 300)` seconds. Token hashes (truncated SHA-256, 16 hex
characters) are used as keys rather than raw tokens to avoid storing
sensitive material. Stale rate-limit entries are cleaned up every
`CLEANUP_INTERVAL_SECONDS=600` (10 minutes) to prevent unbounded dict
growth.

The user model also supports `path_mappings` -- a dict of host-to-container
prefix replacements for translating source paths in search results back to
paths the client can open. Mappings are expanded at config load time via
`_expand_path_str()` in `src/ragling/config.py`.

Key files: `src/ragling/auth/auth.py`, `src/ragling/auth/token_verifier.py`.

---

## Auto-Detection Conventions

When a directory is added to the `watch` configuration, ragling automatically
determines how to index it by checking for marker files. The
`detect_directory_type()` function in `src/ragling/indexers/auto_indexer.py`
implements the marker precedence: `.obsidian/` takes priority over `.git/`,
because a vault with version control is primarily a notes collection, not a
code repository. If neither marker is found, the directory falls back to the
`PROJECT` indexer type, which handles generic document collections.

The `detect_indexer_type_for_file()` variant walks up the directory tree
from a changed file to find the nearest marker, enabling correct routing for
file watcher events without re-scanning the top-level directory. The file
watcher in `src/ragling/watchers/watcher.py` uses a 2-second
debounce via `DebouncedIndexQueue`. When a file change is detected, the
debounce timer resets; only after 2 seconds of inactivity does the queue
flush and invoke the callback with the batched set of changed paths. This
prevents redundant indexing during rapid edits (e.g., saving a file multiple
times in quick succession).

The watcher filters by file extension using a supported extensions set and
skips hidden directories (any path component starting with `.`), with two
exceptions: `.git/HEAD` and files under `.git/refs/` are explicitly allowed
through by `_is_git_state_file()`, since changes to these files signal
branch switches or new commits that should trigger re-indexing.

The system database watcher in `src/ragling/watchers/system_watcher.py` uses
a longer 10-second debounce (`_DEFAULT_DEBOUNCE_SECONDS = 10.0`). This
accounts for the high frequency of WAL file changes during normal SQLite
operations in email clients, Calibre, and RSS readers. A 2-second debounce
would trigger redundant re-indexing on nearly every database checkpoint.

The config watcher uses a 2-second debounce and implements safe fallback: if
the config file cannot be parsed (JSON syntax error, encoding issues), the
watcher logs the error and retains the previous valid configuration rather
than crashing or reverting to defaults.

Key files: `src/ragling/indexers/auto_indexer.py`,
`src/ragling/watchers/watcher.py`,
`src/ragling/watchers/system_watcher.py`.

---

## Error Handling Philosophy

Ragling follows a graceful degradation strategy: the system always starts and
always processes what it can, even when individual components fail. This is
essential for a local tool that indexes diverse, unpredictable content -- a
corrupt PDF should not prevent indexing an entire vault.

Configuration never fails. `load_config()` in `src/ragling/config.py`
catches `JSONDecodeError`, `OSError`, and `UnicodeDecodeError` when reading
the config file and falls back to an empty dict, which produces a `Config`
with all default values. This means the MCP server always starts, even with
a missing, corrupt, or binary config file.

Parsers never raise exceptions to callers. Each parser is expected to catch
all errors internally, log them, and return `None` or an empty result. This
follows the INV-5 invariant from the parsers specification. Helper functions
embody this pattern: `extract_audio_metadata()` in
`src/ragling/document/audio_metadata.py` returns an empty dict on any
failure, and image description via VLM returns an empty string if inference
fails. PDF conversion has a fallback chain: Docling is tried first, and if
it raises `ConversionError`, the system falls back to pypdfium2 for basic
text extraction.

Indexing uses partial-success semantics. Each indexer wraps individual item
processing in try/except/finally blocks, counting errors in the
`IndexResult` dataclass (fields: `indexed`, `skipped`, `errors`,
`error_messages`). A single file that fails to parse or embed does not abort
the entire indexing run. The `_run()` worker loop in `IndexingQueue`
similarly catches exceptions per job, records the failure via
`self._status.record_failure()`, and continues processing the next job.

Database lock handling accounts for external SQLite databases that may be
locked by their owning applications. The `DocStore` uses WAL mode with
`busy_timeout=5000ms` and `_set_wal_mode()` retries with exponential backoff
(5 attempts, base delay 50ms) to handle concurrent initialization.

Embedding batch operations implement a two-level fallback in
`src/ragling/embeddings.py`: batch failure triggers individual retry, and
individual failure triggers truncation retry (256 words). Only connection
errors are immediately re-raised as `OllamaConnectionError`.

---

## Concurrency Model

Ragling's concurrency model is deliberately simple: a single-writer
`IndexingQueue` backed by one daemon worker thread. All indexing operations
-- startup sync, file watcher events, MCP tool invocations -- submit
`IndexJob` items to a `queue.Queue`. The worker thread in
`src/ragling/indexing_queue.py` picks up jobs sequentially via `_run()`,
routing each to the correct indexer through `_process()`.

This eliminates write contention by design: only the worker thread writes to
the database, so there are no locks, no connection pools, and no deadlocks.
The `DocStore` is also inherently thread-safe since only the worker thread
calls indexers that invoke `DocStore.get_or_convert()`.

SQLite databases use WAL (Write-Ahead Logging) mode, which allows concurrent
reads across multiple MCP instances while the single writer thread indexes.
Multiple `ragling serve` processes can serve search queries simultaneously
against the same database; only one performs writes. WAL mode initialization
includes retry logic in `_set_wal_mode()` in `src/ragling/doc_store.py`
because the initial `PRAGMA journal_mode=WAL` requires an exclusive lock
that ignores `busy_timeout`.

Leader election determines which MCP server instance runs the
`IndexingQueue` and watchers. `LeaderLock` in `src/ragling/leader.py` uses
`fcntl.flock()` for kernel-level exclusive locking on a per-group lock file.
The critical advantage of `flock` over PID-based schemes is automatic
cleanup: the kernel releases the lock when the process dies, so there are no
stale lock files, no PID files to garbage-collect, and no heartbeat
mechanisms. The loser becomes a follower (search-only) and starts a retry
thread that re-attempts lock acquisition every 30 seconds. On successful
promotion, the `on_promote` callback starts the full leader infrastructure.

Startup synchronization runs as a daemon thread so the MCP server responds
to search queries immediately while the background scan runs. In
`src/ragling/server.py`, `start_leader_infrastructure()` launches
`run_startup_sync()` in a background thread that sets a `sync_done` event on
completion. The file watcher starts only after sync completes (via a separate
daemon thread waiting on the event), avoiding duplicate processing.

No connection pooling is used. Each operation opens and closes its own
SQLite connection via `_open_conn()` in `IndexingQueue`. This is appropriate
for the CLI/MCP use case where connection overhead is negligible compared to
embedding and conversion costs.

Key files: `src/ragling/indexing_queue.py`, `src/ragling/leader.py`,
`src/ragling/server.py`.

---

## Configuration Patterns

The `Config` class in `src/ragling/config.py` is a frozen dataclass
(`@dataclass(frozen=True)`), making it thread-safe by immutability. Any
attempt to mutate a field raises `FrozenInstanceError`. This is critical
because the config is read by multiple threads (MCP request handlers, the
indexing worker, watchers) without synchronization.

Mutation is handled through `with_overrides(**kwargs)`, which returns a new
`Config` instance via `dataclasses.replace()`. The method also auto-wraps
plain dicts for `watch` and `users` fields into `MappingProxyType`, so
callers do not need to import or construct read-only wrappers manually.
`MappingProxyType` wrapping ensures that even the nested dict fields cannot
be accidentally mutated -- attempting to assign a key raises `TypeError`.

Configuration resolution follows a hierarchical precedence: top-level keys
in the JSON file take priority, then `system_sources` sub-object fields are
promoted as fallbacks, and finally hard-coded defaults in the dataclass field
definitions. The `migrate_config_dict()` function handles legacy keys:
`code_groups` entries are folded into `watch`, `obsidian_vaults` are
duplicated into `watch` while being preserved for obsidian:// URI
construction. Deprecation warnings are logged for migrated keys.

Dynamic configuration reload is supported through getter callables.
`ToolContext` stores a `config_getter: Callable[[], Config]` rather than a
static reference. When `ctx.get_config()` is called, it invokes the getter
for the latest config from `ConfigWatcher`, then applies
`with_overrides(group_name=self.group_name)`. Config changes take effect on
the next tool call without restarting the server. The same pattern applies
to `queue_getter` and `role_getter`.

All paths in the config are expanded at load time. `_expand_path()` calls
`Path.expanduser()` to resolve `~` to the home directory, and
`_expand_path_str()` preserves trailing slashes for path mapping prefixes.
This ensures that downstream code never encounters unexpanded tildes.

Key files: `src/ragling/config.py`, `src/ragling/tools/context.py`.

---

## Indexer Design: Two-Pass Pattern

All source-specific indexers follow a two-pass pattern that separates
discovery from processing.

**Pass 1 -- Discovery.** The indexer traverses its source (filesystem
directory, SQLite database, git history), computing content hashes or
watermark timestamps for each item. It checks whether the item has changed
since the last indexing run by comparing the stored hash or timestamp. Items
that have not changed are counted as `skipped` in the `IndexResult`. This
pass builds a work list of items that need processing.

For file-backed sources, change detection uses SHA-256 file hashes computed
by `file_hash()` in `src/ragling/indexers/base.py`. For system collections
(email, RSS), watermark timestamps record the most recent message date. For
git history, commit SHAs serve as the change marker.

**Pass 2 -- Processing.** Each item in the work list is parsed, chunked into
`Chunk` objects, and embedded via batch Ollama calls. The results are
persisted through `upsert_source_with_chunks()` in
`src/ragling/indexers/base.py`, which performs an atomic delete-then-insert
within a single transaction: old documents and vectors for the source are
removed, new ones are inserted, and the transaction is committed. This
ensures the index is never in an inconsistent state with partial old and new
data for the same source.

Status reporting integrates with `IndexingStatus`: `set_file_total()` is
called during the scan phase, and `file_processed()` is called per item
during processing, enabling progress tracking through the MCP
`rag_indexing_status` tool.

Per-item error isolation ensures robustness: each item's processing is
wrapped in try/except/finally. Errors are counted in `IndexResult.errors`
and their messages appended to `IndexResult.error_messages`, but execution
continues. The `BaseIndexer` abstract class defines the `index()` method
signature that all indexers implement.

Code repositories receive special treatment via `_index_via_factory()` in
`IndexingQueue`: after the git history indexer runs, a separate document pass
(`_run_document_pass()`) indexes non-code files (PDFs, DOCX, etc.) using
`ProjectIndexer`.

Key files: `src/ragling/indexers/base.py`,
`src/ragling/indexers/obsidian.py`.

---

## Embedding Strategy

Embedding generation in `src/ragling/embeddings.py` is designed for
throughput with graceful degradation. The `get_embeddings()` function sends
texts in sub-batches of `_BATCH_SIZE = 32` to the Ollama API. This balances
throughput (fewer HTTP round-trips) against timeout risk (a single massive
batch could exceed the 300-second `_TIMEOUT`). Progress is logged for
multi-batch runs, showing batch ranges against the total count.

When a batch embedding call fails (any exception that is not a connection
error), the system falls back to embedding each text in the batch
individually via `_embed_single_with_retry()`. This isolates the problematic
text: if one out of 32 texts causes an Ollama error, the other 31 still get
embedded successfully.

Individual embedding failures trigger one truncation retry.
`_embed_single_with_retry()` catches the first exception, truncates the text
to 256 words using `_truncate_to_words()`, and retries. This handles texts
that exceed the model's context window or contain problematic tokens. If the
retry also fails, the exception propagates to the caller (the indexer),
which catches it per-item and records the error.

Connection errors are detected early and re-raised as
`OllamaConnectionError` via `_raise_if_connection_error()`, which checks for
"connect" or "refused" substrings in the exception message. This
distinguishes between "Ollama is not running" (fatal, should propagate
immediately) and "this particular text caused an error" (recoverable via
fallback). The error message helpfully includes the configured `ollama_host`
if set, or suggests `ollama serve` if using the default localhost.

Key file: `src/ragling/embeddings.py`.

---

## Dependency Injection

Tool functions in ragling's MCP server use explicit dependency injection
through the `ToolContext` dataclass in `src/ragling/tools/context.py`,
replacing the closure capture pattern that was previously used in
`create_server()`. Each tool function receives a `ToolContext` instance that
provides access to shared state.

The key design choice is that `ToolContext` stores callable getters rather
than static references for values that change at runtime:
`config_getter` returns the latest config from `ConfigWatcher`,
`queue_getter` returns the current indexing queue (may be `None` for
followers), and `role_getter` returns `"leader"` or `"follower"`. Tool
functions always see current state without restart or re-registration.

Static fields include `group_name`, `server_config` (initial config,
fallback if no getter), and `indexing_status`. The `get_config()` method
applies `with_overrides(group_name=self.group_name)` to the getter result,
ensuring the group is always set correctly.

Key file: `src/ragling/tools/context.py`.

---

## Naming Conventions

Ragling follows standard Python naming conventions with a few
codebase-specific patterns. Private functions and module-level helpers use a
leading underscore (`_function()`, `_CONSTANT`). Public constants use
`UPPER_CASE` (e.g., `DEFAULT_CONFIG_PATH`, `RESERVED_COLLECTION_NAMES`).
Classes use `PascalCase` (`DocStore`, `IndexingQueue`, `LeaderLock`).
Module-internal constants use `_UPPER_CASE` with a leading underscore (e.g.,
`_TIMEOUT`, `_WAL_RETRIES`, `_FILTERED_OVERSAMPLING`).

Frozen dataclasses are used for thread-shared configuration (`Config`,
`EnrichmentConfig`, `IndexJob`), while plain dataclasses are used for
mutable state (`IndexResult`, `IndexRequest`, `ToolContext`). This
convention signals thread-safety guarantees at the type level.

Type hints use `from __future__ import annotations` for PEP 604 syntax
(`X | None` instead of `Optional[X]`). Input parameters prefer `Sequence`
over `list` for flexibility, while return types use concrete `list` or
`tuple`. The `TYPE_CHECKING` guard is used for imports that are only needed
for type annotations, avoiding circular imports and reducing startup time
(e.g., `IndexingQueue`, `DocStore`, `Config` in several modules).

Docstrings follow Google style with `Args:`, `Returns:`, and `Raises:`
sections. Every public class and function has a docstring. Module-level
docstrings describe the module's purpose and key design decisions (e.g., the
thread-safety note at the top of `src/ragling/indexing_queue.py`).

Import ordering follows the standard convention: stdlib, then third-party,
then local. `TYPE_CHECKING`-guarded imports are placed after regular imports
in their own block. Logging uses `logging.getLogger(__name__)` at module
level, with messages at appropriate levels: `info` for milestones, `warning`
for degraded operation, `error` for non-crashing failures, and `exception`
for unexpected errors with tracebacks.

---

## Search Parameter Tuning

The hybrid search engine in `src/ragling/search/search.py` combines vector
similarity and full-text search using Reciprocal Rank Fusion (RRF). The
default weights are 0.7 for vector results and 0.3 for FTS results, with an
RRF `k` parameter of 60, following the findings of Cormack et al. (2009) on
rank fusion effectiveness. These defaults are configurable per-deployment via
the `SearchDefaults` dataclass in the config.

Oversampling compensates for post-retrieval filtering. Unfiltered queries
fetch `3x` the requested `top_k` (`_UNFILTERED_OVERSAMPLING = 3`). Filtered
queries (collection, source type, date range, sender, author, subsystem, or
section type) increase to `50x` (`_FILTERED_OVERSAMPLING = 50`) because
filtering can discard a large fraction of candidates.

A shared metadata cache (`metadata_cache: dict[int, sqlite3.Row]`) is passed
between vector and FTS search paths so metadata rows loaded during vector
filtering are reused during FTS filtering. `_batch_load_metadata()` loads
metadata for all candidate IDs in a single query, and `_apply_filters()`
checks candidates in memory rather than constructing complex SQL WHERE
clauses.

Stale source detection uses `os.stat()` to check whether the file backing a
search result still exists. Stat results are cached per unique source path
within a search request. Results from deleted files are marked `stale=True`
in `SearchResult`, allowing clients to display appropriate warnings.

Key file: `src/ragling/search/search.py`.

---

## Caching Strategy

Ragling uses multiple caching layers to avoid redundant computation.

The `DocStore` in `src/ragling/doc_store.py` is the primary cache. It stores
Docling conversion results keyed by `(source_path, content_hash,
config_hash)`. The `content_hash` is a SHA-256 digest of file contents via
`file_hash()`. The `config_hash` is a 16-character hex string from
`converter_config_hash()` in `src/ragling/document/docling_convert.py`,
which hashes the JSON-serialized pipeline configuration. When any enrichment
setting changes, the config hash changes, and cached conversions are
automatically invalidated on next access. The DocStore is shared across
groups -- all MCP instances benefit from the same conversion cache.

The `@lru_cache` decorator is used for singletons in the document conversion
pipeline. `get_converter()` caches the `DocumentConverter` instance by its
configuration parameters. `_get_tokenizer()` caches `HuggingFaceTokenizer`
instances by model ID and max token count. `_get_vlm_engine()` caches the
VLM engine by Ollama host. These caches are safe because `IndexingQueue`
uses a single worker thread, as documented in the comment above
`get_converter()`. If the concurrency model ever changes to multiple worker
threads, these caches would need thread-safe wrappers.

The metadata cache within search operations avoids redundant database
queries. When `_apply_filters()` processes vector search candidates, it
batch-loads metadata rows into a dict keyed by document ID. This dict is
passed to the FTS filtering path, so metadata for documents appearing in
both result sets is loaded only once.

No external cache services (Redis, Memcached) are used, consistent with the
"everything runs locally" philosophy. All caching is SQLite-backed (DocStore)
or in-process (`lru_cache`, dict caches), keeping the deployment footprint
minimal.

Key files: `src/ragling/doc_store.py`,
`src/ragling/document/docling_convert.py`.
