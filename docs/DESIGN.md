# Ragling Design

Design patterns, conventions, and rationale for the ragling codebase.
For system structure, schemas, and data flow, see [Architecture](ARCHITECTURE.md).

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

Ragling uses Docling's `HybridChunker` because it preserves document
structure. Unlike naive text splitting, `HybridChunker` keeps headings,
tables, code blocks, and list items intact as atomic units, splitting only
when a structural element exceeds the token budget. The default chunk size is 256 tokens with 50 tokens of overlap,
aligned to the bge-m3 tokenizer via a `HuggingFaceTokenizer` wrapper.

`_get_tokenizer()` in `src/ragling/document/docling_convert.py` creates the
tokenizer and is `@lru_cache`-decorated to avoid re-instantiating
`AutoTokenizer` on every call.

The `contextualize()` method on each chunk prepends the heading hierarchy
as a context prefix, so a chunk deep in a nested section carries its full
heading path. This is critical for retrieval quality: a chunk about
"Installation" under "macOS" under "Getting Started" gets the full
breadcrumb, making it distinguishable from an "Installation" chunk in
a different context.

Enrichment metadata -- picture descriptions from VLM inference, table
captions from TableFormer, code language tags from code enrichment -- comes
from Docling's `doc_items` (`PictureItem`, `TableItem`, `CodeItem` types)
and is stored in the chunk's metadata dict, persisted as JSON in the
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

Ragling supports two transports with different authentication models. Stdio,
used when a local IDE or CLI launches the MCP server, requires no
authentication and grants full access to all collections. SSE, used for
remote or multi-user access over HTTPS, requires Bearer token
authentication with TLS.

SSE auth starts with a Bearer token in the Authorization header.
`RaglingTokenVerifier.verify_token()` in
`src/ragling/auth/token_verifier.py` delegates to `resolve_api_key()` in
`src/ragling/auth/auth.py`, which iterates over all configured users and
uses `hmac.compare_digest()` for timing-safe comparison against each stored
`api_key`. This constant-time comparison prevents side-channel attacks that could leak
key prefixes through response timing. On success, it returns a `UserContext`
dataclass containing the `username`, `system_collections` list, and
`path_mappings` dict.

Visibility rules determine which collections a user can search: their own
collection (named after their username), the `global` collection if
configured, and any collections in their `system_collections` field (e.g.,
`["email", "calibre"]`). Stdio connections bypass visibility and see all
collections. The
`visible_collections()` method on `UserContext` computes this list.

Rate limiting protects against brute-force API key guessing.
`RaglingTokenVerifier` tracks failed attempts per hashed token with
exponential backoff: after `MAX_FAILURES=5` failures, subsequent attempts
are rejected with `RateLimitedError` and a backoff of
`min(2^count, 300)` seconds. Token hashes (truncated SHA-256, 16 hex characters) serve as keys rather
than raw tokens to avoid storing sensitive material. Stale rate-limit entries are purged every `CLEANUP_INTERVAL_SECONDS=600`
(10 minutes) to prevent unbounded dict growth.

The user model also supports `path_mappings` -- a dict of host-to-container
prefix replacements that translate source paths in search results to paths
the client can open. Mappings are expanded at config load time via
`_expand_path_str()` in `src/ragling/config.py`.

Key files: `src/ragling/auth/auth.py`, `src/ragling/auth/token_verifier.py`.

---

## Auto-Detection Conventions

When a directory is added to `watch`, ragling determines how to index it by
checking for marker files. `detect_directory_type()` in
`src/ragling/indexers/auto_indexer.py` implements the marker precedence:
`.obsidian/` takes priority over `.git/`, because a vault with version
control is primarily a notes collection, not a code repository. If neither
marker is found, the directory falls back to the `PROJECT` indexer type,
which handles generic document collections.

`detect_indexer_type_for_file()` walks up the directory tree from a changed
file to find the nearest marker, routing file watcher events correctly
without re-scanning the top-level directory. The file watcher in
`src/ragling/watchers/watcher.py` uses a 2-second debounce via
`DebouncedIndexQueue`. Each file change resets the timer; only after 2
seconds of inactivity does the queue flush and invoke the callback with the
batched changed paths. This prevents redundant indexing during rapid edits
(e.g., saving a file multiple times in quick succession).

The watcher filters by file extension and skips hidden directories (any path
component starting with `.`), with two exceptions: `.git/HEAD` and files
under `.git/refs/` pass through via `_is_git_state_file()`, since changes to
these files signal branch switches or new commits that should trigger
re-indexing.

The system database watcher in `src/ragling/watchers/system_watcher.py` uses
a longer 10-second debounce (`_DEFAULT_DEBOUNCE_SECONDS = 10.0`) because
email clients, Calibre, and RSS readers produce frequent WAL file changes
during normal SQLite operations. A 2-second debounce would trigger redundant
re-indexing on nearly every database checkpoint.

The config watcher uses a 2-second debounce with safe fallback: if the
config file cannot be parsed (JSON syntax error, encoding issues), the
watcher logs the error and retains the previous valid configuration rather
than crashing or reverting to defaults.

Key files: `src/ragling/indexers/auto_indexer.py`,
`src/ragling/watchers/watcher.py`,
`src/ragling/watchers/system_watcher.py`.

---

## Error Handling Philosophy

Ragling degrades gracefully: it always starts and always processes what it
can, even when individual components fail. A corrupt PDF should not prevent
indexing an entire vault.

Configuration never fails. `load_config()` in `src/ragling/config.py`
catches `JSONDecodeError`, `OSError`, and `UnicodeDecodeError` and falls
back to an empty dict, producing a `Config` with all default values. The MCP
server always starts, even with a missing, corrupt, or binary config file.

Parsers never raise exceptions to callers. Each parser catches all errors
internally, logs them, and returns `None` or an empty result (INV-5
invariant). `extract_audio_metadata()` in
`src/ragling/document/audio_metadata.py` returns an empty dict on any
failure; VLM image description returns an empty string if inference fails.
PDF conversion chains fallbacks: Docling first, then pypdfium2 for basic
text extraction if Docling raises `ConversionError`.

Indexing uses partial-success semantics. Each indexer wraps individual item
processing in try/except/finally blocks, counting errors in `IndexResult`
(fields: `indexed`, `skipped`, `errors`, `error_messages`). A single file
that fails to parse or embed does not abort the entire run. The `_run()`
worker loop in `IndexingQueue` catches exceptions per job, records the
failure via `self._status.record_failure()`, and continues to the next job.

Database lock handling accounts for external SQLite databases locked by
their owning applications. `DocStore` uses WAL mode with
`busy_timeout=5000ms`, and `_set_wal_mode()` retries with exponential
backoff (5 attempts, base delay 50ms) for concurrent initialization.

Embedding batch operations in `src/ragling/embeddings.py` implement a
two-level fallback: batch failure triggers individual retry; individual
failure triggers truncation retry (256 words). Only connection errors are
re-raised immediately as `OllamaConnectionError`.

---

## Concurrency Model

Ragling's concurrency model is deliberately simple: a single-writer
`IndexingQueue` backed by one daemon worker thread. All indexing operations
-- startup sync, file watcher events, MCP tool invocations -- submit
`IndexJob` items to a `queue.Queue`. The worker thread picks up jobs
sequentially via `_run()`, routing each to the correct indexer through
`_process()`.

This eliminates write contention by design: only the worker thread writes to
the database, so there are no locks, no connection pools, and no deadlocks.
`DocStore` is inherently thread-safe since only the worker thread calls
indexers that invoke `DocStore.get_or_convert()`.

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
`flock`'s advantage over PID-based schemes is automatic cleanup: the kernel
releases the lock when the process dies, leaving no stale lock files, no PID
files to garbage-collect, and no heartbeat mechanisms. The loser becomes a
follower (search-only) and starts a retry thread that re-attempts lock
acquisition every 30 seconds. On successful
promotion, the `on_promote` callback starts the full leader infrastructure.

Startup sync runs as a daemon thread so the MCP server responds to search
queries immediately while the background scan proceeds. In
`src/ragling/server.py`, `start_leader_infrastructure()` launches
`run_startup_sync()` in a background thread that sets a `sync_done` event on
completion. The file watcher starts only after sync completes (via a separate
daemon thread waiting on the event), avoiding duplicate processing.

No connection pooling is used. Each operation opens and closes its own
SQLite connection via `_open_conn()` in `IndexingQueue`. Connection overhead
is negligible compared to embedding and conversion costs in this CLI/MCP use
case.

Key files: `src/ragling/indexing_queue.py`, `src/ragling/leader.py`,
`src/ragling/server.py`.

---

## Configuration Patterns

`Config` in `src/ragling/config.py` is a frozen dataclass
(`@dataclass(frozen=True)`), thread-safe by immutability. Any mutation
attempt raises `FrozenInstanceError`. This matters because multiple threads
(MCP request handlers, the indexing worker, watchers) read the config
without synchronization.

`with_overrides(**kwargs)` returns a new `Config` via
`dataclasses.replace()`, auto-wrapping plain dicts for `watch` and `users`
into `MappingProxyType` so callers need not construct read-only wrappers.
`MappingProxyType` ensures that even nested dict fields cannot be mutated
-- assigning a key raises `TypeError`.

Configuration resolution follows hierarchical precedence: top-level JSON
keys take priority, then `system_sources` sub-object fields as fallbacks,
then hard-coded defaults in the dataclass field definitions.
`migrate_config_dict()` handles legacy keys: `code_groups` entries fold into
`watch`, `obsidian_vaults` are duplicated into `watch` while preserved for
obsidian:// URI construction. Deprecation warnings are logged for migrated
keys.

Dynamic reload works through getter callables. `ToolContext` stores a
`config_getter: Callable[[], Config]` rather than a static reference.
`ctx.get_config()` invokes the getter for the latest config from
`ConfigWatcher`, then applies `with_overrides(group_name=self.group_name)`.
Config changes take effect on the next tool call without restarting the
server. The same pattern applies to `queue_getter` and `role_getter`.

All config paths are expanded at load time. `_expand_path()` calls
`Path.expanduser()` to resolve `~`, and `_expand_path_str()` preserves
trailing slashes for path mapping prefixes. Downstream code never encounters
unexpanded tildes.

Key files: `src/ragling/config.py`, `src/ragling/tools/context.py`.

---

## Indexer Design: Two-Pass Pattern

All indexers follow a two-pass pattern that separates discovery from
processing.

**Pass 1 -- Discovery.** The indexer traverses its source (filesystem
directory, SQLite database, git history), computing content hashes or
watermark timestamps for each item. It compares the stored hash or timestamp
to detect changes. Unchanged items are counted as `skipped` in
`IndexResult`. This pass builds a work list of items needing processing.

For file-backed sources, change detection uses SHA-256 file hashes computed
by `file_hash()` in `src/ragling/indexers/base.py`. For system collections
(email, RSS), watermark timestamps record the most recent message date. For
git history, commit SHAs serve as the change marker.

**Pass 2 -- Processing.** Each work-list item is parsed, chunked into
`Chunk` objects, and embedded via batch Ollama calls.
`upsert_source_with_chunks()` in `src/ragling/indexers/base.py` persists
results atomically: within a single transaction, it deletes old documents
and vectors for the source, inserts new ones, and commits. The index never
holds partial old and new data for the same source.

Status reporting integrates with `IndexingStatus`: `set_file_total()` runs
during the scan phase, `file_processed()` runs per item during processing,
enabling progress tracking through the MCP `rag_indexing_status` tool.

Per-item error isolation wraps each item in try/except/finally. Errors
increment `IndexResult.errors` and append to `IndexResult.error_messages`,
but execution continues. `BaseIndexer` defines the `index()` method
signature that all indexers implement.

Code repositories receive special treatment via `_index_via_factory()` in
`IndexingQueue`: after the git history indexer runs, a separate document pass
(`_run_document_pass()`) indexes non-code files (PDFs, DOCX, etc.) using
`ProjectIndexer`.

Key files: `src/ragling/indexers/base.py`,
`src/ragling/indexers/obsidian.py`.

---

## Embedding Strategy

`get_embeddings()` in `src/ragling/embeddings.py` sends texts in sub-batches
of `_BATCH_SIZE = 32` to the Ollama API, balancing throughput (fewer HTTP
round-trips) against timeout risk (a single massive batch could exceed the
300-second `_TIMEOUT`). Progress is logged for multi-batch runs, showing
batch ranges against the total count.

When a batch call fails (any exception except connection errors), the system
falls back to embedding each text individually via
`_embed_single_with_retry()`. If one text out of 32 causes an Ollama error,
the other 31 still embed successfully.

Individual failures trigger one truncation retry.
`_embed_single_with_retry()` catches the first exception, truncates the text
to 256 words via `_truncate_to_words()`, and retries. This handles texts
that exceed the model's context window or contain problematic tokens. If the
retry also fails, the exception propagates to the indexer, which catches it
per-item and records the error.

`_raise_if_connection_error()` detects connection errors early by checking
for "connect" or "refused" substrings and re-raises them as
`OllamaConnectionError`. This distinguishes "Ollama is not running" (fatal,
propagate immediately) from "this text caused an error" (recoverable via
fallback). The error message includes the configured `ollama_host` if set,
or suggests `ollama serve` if using the default localhost.

Key file: `src/ragling/embeddings.py`.

---

## Dependency Injection

MCP tool functions use explicit dependency injection through `ToolContext`
in `src/ragling/tools/context.py`, replacing the closure capture pattern
formerly used in `create_server()`. Each tool function receives a
`ToolContext` instance that provides access to shared state.

`ToolContext` stores callable getters rather than static references for
values that change at runtime:
`config_getter` returns the latest config from `ConfigWatcher`,
`queue_getter` returns the current indexing queue (may be `None` for
followers), and `role_getter` returns `"leader"` or `"follower"`. Tool functions always see current state without restart or
re-registration.

Static fields include `group_name`, `server_config` (initial config;
fallback if no getter), and `indexing_status`. `get_config()` applies
`with_overrides(group_name=self.group_name)` to the getter result, ensuring
the group is always set.

Key file: `src/ragling/tools/context.py`.

---

## Naming Conventions

Ragling follows standard Python naming with a few codebase-specific
patterns. Private functions and module-level helpers use a leading underscore
(`_function()`, `_CONSTANT`). Public constants use `UPPER_CASE` (e.g.,
`DEFAULT_CONFIG_PATH`, `RESERVED_COLLECTION_NAMES`).
Classes use `PascalCase` (`DocStore`, `IndexingQueue`, `LeaderLock`).
Module-internal constants use `_UPPER_CASE` with a leading underscore (e.g.,
`_TIMEOUT`, `_WAL_RETRIES`, `_FILTERED_OVERSAMPLING`).

Frozen dataclasses represent thread-shared configuration (`Config`,
`EnrichmentConfig`, `RerankerConfig`, `IndexJob`); plain dataclasses
represent mutable state (`IndexResult`, `IndexRequest`, `ToolContext`). This convention signals
thread-safety guarantees at the type level.

Type hints use `from __future__ import annotations` for PEP 604 syntax
(`X | None` instead of `Optional[X]`). Input parameters prefer `Sequence`
over `list` for flexibility; return types use concrete `list` or `tuple`.
`TYPE_CHECKING` guards imports needed only for type annotations, avoiding
circular imports and reducing startup time (e.g., `IndexingQueue`,
`DocStore`, `Config` in several modules).

Docstrings follow Google style with `Args:`, `Returns:`, and `Raises:`
sections. Every public class and function has a docstring. Module-level
docstrings state the module's purpose and key design decisions (e.g., the
thread-safety note atop `src/ragling/indexing_queue.py`).

Imports follow stdlib, third-party, local order. `TYPE_CHECKING`-guarded
imports sit after regular imports in their own block. Logging uses
`logging.getLogger(__name__)` at module level: `info` for milestones,
`warning` for degraded operation, `error` for non-crashing failures,
`exception` for unexpected errors with tracebacks.

---

## Search Parameter Tuning

The hybrid search engine in `src/ragling/search/search.py` combines vector
similarity and full-text search using Reciprocal Rank Fusion (RRF). Default
weights are 0.7 vector, 0.3 FTS, with RRF `k` of 60 per Cormack et al.
(2009). These defaults are configurable per-deployment via `SearchDefaults`
in the config.

Oversampling compensates for post-retrieval filtering. Unfiltered queries
fetch `3x` the requested `top_k` (`_UNFILTERED_OVERSAMPLING = 3`). Filtered
queries (collection, source type, date range, sender, author, subsystem, or
section type) increase to `50x` (`_FILTERED_OVERSAMPLING = 50`) because
filtering can discard a large fraction of candidates.

A shared metadata cache (`metadata_cache: dict[int, sqlite3.Row]`) passes
between vector and FTS search paths so metadata rows loaded during vector
filtering are reused during FTS filtering. `_batch_load_metadata()` loads
metadata for all candidate IDs in a single query; `_apply_filters()` checks
candidates in memory rather than constructing complex SQL WHERE clauses.

Stale source detection uses `os.stat()` to check whether a result's
backing file still exists. Stat results are cached per unique source path
within a search request. Results from deleted files are marked `stale=True`
in `SearchResult`, letting clients display warnings.

### Cross-Encoder Rescoring

RRF produces well-ordered results but compresses scores (typically 0.001–0.016),
making them useless for confidence thresholding. When a reranker endpoint is
configured, `rescore()` in `src/ragling/search/rescore.py` sends the top
`3 × top_k` candidates (controlled by `_RESCORE_OVERSAMPLE`) to an Infinity
cross-encoder server. The cross-encoder returns calibrated relevance scores
(0.0–1.0) that replace the RRF scores, enabling consumers to filter by score
quality.

#### Why scoring over ranking

Cross-encoder models fall into two categories by training objective:

- **Ranking losses** (contrastive, triplet, listwise) optimize relative ordering
  metrics like NDCG@10. Scores reflect "better than" relationships but carry no
  absolute meaning — a score of 0.7 from one query says nothing about 0.7 from
  another.
- **Classification losses** (binary cross-entropy) train the model to predict
  P(relevant | query, document). Scores approximate calibrated probabilities:
  0.9 means "very likely relevant" regardless of query. This enables threshold-
  based filtering (e.g., `min_score=0.3` to drop noise).

Ragling uses rescoring for **score calibration**, not re-ranking. RRF already
orders results well from two independent signals. What RRF lacks is a
calibrated confidence score that consumers can threshold. The design therefore
requires models trained with binary cross-entropy.

#### Model selection: `mxbai-rerank-xsmall-v1`

The default model is `mixedbread-ai/mxbai-rerank-xsmall-v1` (~71M params,
12-layer DeBERTa-v2 architecture). Selection criteria:

| Criterion | mxbai-rerank-xsmall-v1 | bge-reranker-v2-m3 | mxbai-rerank-base-v1 |
|-----------|------------------------|--------------------|----------------------|
| Params | ~71M | 568M | ~200M |
| Latency (30 docs, batched, CPU) | ~850ms | — | — |
| NDCG@10 (BEIR avg) | 43.9 | 68.0 | 59.2 |
| Score separation | Good (0.0–1.0 spread) | Good | Good |

`mxbai-rerank-xsmall-v1` wins on three axes:

1. **Latency budget.** Rescoring 30 candidates takes ~850ms on CPU (batched).
   Infinity adds HTTP overhead but provides native batch inference.
2. **Score calibration quality.** The model produces scores spread across the
   full 0.0–1.0 range, making `min_score` thresholds meaningful.
3. **Resource footprint.** ~71M params fits comfortably alongside Ollama's
   embedding model on machines without a dedicated GPU. Larger rerankers compete
   for VRAM with the embedding model.
4. **Sufficient ranking quality.** NDCG@10 trails larger models, but RRF already
   provides strong ordering from two independent signals. The cross-encoder
   calibrates scores rather than fundamentally reorders.

Users who want higher ranking accuracy at the cost of latency can set
`reranker.model` to a larger model in their config.

#### Why Infinity over Ollama

Cross-encoders require paired (query, document) inference — they cannot encode
documents independently. For N candidates, the model runs N forward passes.

Benchmarked on CPU with `mxbai-rerank-xsmall-v1` (30 candidates, ~200 tokens
each):

| Mode | 30 candidates | Notes |
|------|--------------|-------|
| Batched (as Infinity does) | ~850ms | Single forward pass with batch dimension |
| Sequential (as Ollama would) | ~2,900ms | 30 individual forward passes |

Batching provides a ~3.4x speedup on CPU. Infinity serves the model with native
batch inference through its `/rerank` endpoint. Ollama lacks cross-encoder
support — its generation pipeline is optimized for token-by-token autoregressive
output, not single-pass classification.

#### Compound oversampling

When rescoring is active, `perform_search` requests `3 × top_k` results from
the `search()` function (`_RESCORE_OVERSAMPLE = 3`). Inside `search()`, the
vector and FTS retrieval paths apply their own `_UNFILTERED_OVERSAMPLING = 3`
(or `_FILTERED_OVERSAMPLING = 50` for filtered queries). The effective
candidate count for unfiltered queries reaches `top_k × 3 × 3 = 9×`.

This compound oversampling serves two distinct purposes: the outer 3x gives the
cross-encoder enough candidates for meaningful score discrimination, while the
inner 3x gives RRF merge enough candidates from each retrieval path. For
filtered queries the inner multiplier rises to 50x to compensate for
post-retrieval filtering.

#### Connection pooling and TLS

`rescore.py` maintains a module-level `httpx.Client` singleton (`_get_client()`)
for TCP connection reuse across calls. In batch search, this avoids creating
N separate TCP connections for N queries. The client initializes lazily and
recreates itself when the `verify_tls` setting changes.

For local Infinity deployments using self-signed TLS certificates, set
`reranker.verify_tls` to `false` in the config.

#### Graceful degradation

On any failure — connection error, timeout, malformed response, out-of-bounds
index — rescoring preserves the original RRF scores and marks the response
`"reranked": false` so consumers know the scores lack calibration. The
`reranked` flag appears in every search response; consumers never need to check
for key existence.

The `perform_batch_search` function returns per-query reranked flags
(`list[bool]`), allowing each query to succeed or fail independently. The MCP
tool layer (`batch_search.py`) aggregates these into a single all-or-nothing
flag for the response: `true` only when every query rescored successfully.

Key files: `src/ragling/search/search.py`, `src/ragling/search/rescore.py`.

---

## Caching Strategy

Ragling uses multiple caching layers to avoid redundant computation.

`DocStore` in `src/ragling/doc_store.py` is the primary cache. It stores
Docling conversion results keyed by `(source_path, content_hash,
config_hash)`. `content_hash` is a SHA-256 digest of file contents via
`file_hash()`. `config_hash` is a 16-character hex string from
`converter_config_hash()` in `src/ragling/document/docling_convert.py`,
which hashes the JSON-serialized pipeline configuration. When any enrichment
setting changes, the config hash changes, automatically invalidating cached
conversions on next access. The DocStore is shared across groups -- all MCP
instances benefit from the same conversion cache.

`@lru_cache` provides singletons in the document conversion pipeline:
`get_converter()` caches the `DocumentConverter` by configuration,
`_get_tokenizer()` caches `HuggingFaceTokenizer` by model ID and max token
count, `_get_vlm_engine()` caches the VLM engine by Ollama host. These
caches are safe because `IndexingQueue` uses a single worker thread, as
documented above `get_converter()`. Multiple worker threads would require
thread-safe wrappers.

The metadata cache within search operations avoids redundant database
queries. `_apply_filters()` batch-loads metadata rows into a dict keyed by
document ID during vector search, then passes this dict to FTS filtering.
Metadata for documents appearing in both result sets loads only once.

No external cache services (Redis, Memcached) are used, consistent with the
"everything runs locally" philosophy. All caching is SQLite-backed (DocStore)
or in-process (`lru_cache`, dict caches), keeping the deployment footprint
minimal.

Key files: `src/ragling/doc_store.py`,
`src/ragling/document/docling_convert.py`.

---

## MCP Tool Registration

MCP tools use explicit dependency injection through `ToolContext` in
`src/ragling/tools/context.py`, replacing the closure capture pattern
formerly used in `create_server()`. Each tool module follows an identical
structure: a `register(mcp: FastMCP, ctx: ToolContext)` function that
defines the tool implementation inside itself using `@mcp.tool()`.

`ToolContext` stores callable getters for runtime-changing values
(`config_getter`, `queue_getter`, `role_getter`) and static fields for fixed
values (`group_name`, `server_config`, `indexing_status`). Tool functions
call `ctx.get_config()` for the latest config with group name applied, and
`ctx.get_queue()` for the current indexing queue (`None` for followers).

`register_all_tools()` in `src/ragling/tools/__init__.py` orchestrates
registration: it imports all tool modules and calls `register(mcp, ctx)` on
each. All tools share the same `ToolContext` instance.

Key patterns within tool modules:

- **Lazy imports.** Dependencies are imported inside the tool function body, not
  at module level. This avoids circular imports and reduces startup time.
- **TYPE_CHECKING blocks.** `FastMCP` and `ToolContext` are imported under
  `TYPE_CHECKING` so type hints work without runtime import cost.
- **Error dict returns.** Tools return `{"error": "message"}` dicts for
  failures rather than raising exceptions, keeping MCP responses well-formed.
- **Status inclusion.** Tools append `indexing_status.to_dict()` to responses
  when indexing is active, giving clients progress visibility.

Key files: `src/ragling/tools/context.py`, `src/ragling/tools/__init__.py`,
`src/ragling/mcp_server.py`.

---

## Testing Strategy

Tests live in `tests/`, one file per major module. The project uses strict
TDD (red-green-refactor) -- no implementation code without a failing test
driving it (see `CONTRIBUTING.md`).

Shared test helpers in `tests/helpers.py` (extracted in PR #58) provide three
factory functions that standardize test setup:

- `make_test_conn(tmp_path)` — creates an initialized SQLite database with
  small embedding dimensions (`EMBED_DIM=4`) for fast tests.
- `make_test_config(tmp_path, **overrides)` — creates a `Config` with test
  defaults, accepting keyword overrides for any field.
- `fake_embeddings(texts, config)` — returns fixed-dimension fake embedding
  vectors, avoiding Ollama dependency in tests.

Database tests use real SQLite with 4-dimensional vectors instead of full
1024-dimensional embeddings, keeping tests fast while exercising the actual
SQL schema and sqlite-vec operations. Extension loading tests are gated
behind `requires_sqlite_extensions` for environments where
`enable_load_extension()` is unavailable.

External dependencies (Ollama, Docling) are patched via
`unittest.mock.patch`; internal SQLite operations use real databases via
`tmp_path` fixtures. This catches integration issues that pure mocking would
miss.

`@pytest.mark.parametrize` is used for combinatorial testing of config
variants, CLI arguments, and format dispatch. Autouse fixtures (e.g.,
`_clear_caches` in `test_docling_convert.py`) ensure `@lru_cache` singletons
are reset between tests.

Key files: `tests/helpers.py`, `tests/conftest.py`.
