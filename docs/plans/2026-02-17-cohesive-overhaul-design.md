# Cohesive Overhaul Design

A single design covering 17 issues identified during architectural review: TLS security, unified sync engine, indexing status, thread safety, search optimization, and code quality.

---

## Architectural Decisions

These decisions were validated during the brainstorming session and inform all phases.

### Single IndexingQueue + Single Worker Thread

All indexing requests (startup sync, watcher events, MCP tool calls, system collection polling) submit work items to one `queue.Queue`. A single dedicated daemon thread processes them sequentially. This eliminates an entire class of thread-safety bugs by design: only one thread ever writes to the DB or calls Ollama for embeddings.

Rationale: Ollama embedding is the bottleneck (not DB writes), so serialized indexing loses nothing. Concurrent writes would require per-connection DB isolation and careful locking for minimal throughput gain on a local single-user system.

### Self-Signed CA for TLS

Generate a local Certificate Authority and server certificate as files in `~/.ragling/tls/`. Nothing enters the system keychain. Only processes explicitly given the CA cert file can verify the connection. Containers mount `ca.pem` read-only.

Rationale: mkcert installs into the login keychain, affecting all apps running as that user. Self-signed CA is fully isolated to ragling consumers.

### Hybrid Monitoring for System Collections

Watch SQLite database files (email, calibre, RSS) for modification as a cheap "something changed" signal. On change, check watermarks to determine if new content exists. If yes, submit an indexing job. Debounce at 10 seconds (longer than file watcher's 2s) because WAL files change frequently.

Rationale: Combines responsiveness of file watching with precision of watermark checks. Reuses the existing debounce queue infrastructure.

### Stat-Based Stale Detection at Search Time

After search returns top-K results (typically 10), call `os.stat()` on each source path. One syscall gives both existence and mtime. Compare mtime against stored `file_modified_at`. Flag stale results in response metadata. Cost: sub-millisecond for 10 local files.

Rationale: Strictly better than exists-only check at the same cost. Catches both deleted and modified-but-not-yet-reindexed files.

### Frozen Config

Make `Config` a frozen dataclass with a `with_overrides()` method. Each operation gets its own derived config snapshot. Eliminates shared mutable state across threads.

### FTS5 Query Escaping

Per SQLite FTS5 spec (section 3.1) and established best practice: double any `"` in user input, wrap the entire string in double quotes. This treats input as a literal phrase, preventing FTS syntax abuse. SQL parameterization handles injection separately.

---

## Phase 1 — Code Quality Cleanup

### Scope

- **Hash consolidation**: Delete duplicate `_file_hash()` in `doc_store.py`. Import `file_hash` from `indexers/base.py` everywhere.
- **Extension consolidation**: Delete `_SUPPORTED_EXTENSIONS` from `sync.py`. Add `is_supported_extension()` helper to `project.py` backed by `_EXTENSION_MAP`. Replace all usages.
- **Docstring improvement**: Rewrite `rag_search` tool docstring in `mcp_server.py` to follow Pythonic conventions with clear parameter descriptions, return format, and usage examples.
- **Duplicate prevention verification**: Add a test confirming that two-pass scans (e.g., git repo containing PDFs) don't produce duplicate entries. `UNIQUE(collection_id, source_path)` and `upsert_source_with_chunks` delete-then-reinsert already handle this — verify, don't fix.

### Process

Implement only. This phase is itself a simplification effort.

### Pause

Compaction directive: `"compact phase 1: code cleanup complete. hash/extension consolidated, docstring updated, duplicate prevention tested."`

---

## Phase 2 — Config Immutability

### Scope

Make `Config` a frozen dataclass with a `with_overrides()` method:

```python
@dataclass(frozen=True)
class Config:
    db_path: Path = ...
    group_name: str = "default"
    # ... all existing fields ...

    def with_overrides(self, **kwargs) -> "Config":
        """Return a new Config with specified fields replaced."""
        import dataclasses
        return dataclasses.replace(self, **kwargs)
```

Fix all mutation sites:

- `mcp_server.py` (~lines 437, 493): Replace `config.group_name = group_name` with `local_config = server_config.with_overrides(group_name=group_name)`.
- `cli.py`: Set `group_name` at config creation time via `config = load_config().with_overrides(group_name=group)`.
- Any other mutation sites discovered during implementation.

### Impact

Most callers only read Config. The frozen constraint surfaces any hidden mutation at the point of change (AttributeError), making thread-safety bugs impossible to introduce silently.

### Process

1. **Worker/coach pairing**: Implement with TDD — red/green/refactor.
2. **Code-simplification agent**: Run twice after implementation.
3. **Architect review**: Verify all mutation sites are converted, no frozen violations remain.
4. **Pause**.

### Pause

Compaction directive: `"compact phase 2: config immutability complete. frozen dataclass with with_overrides(), all mutation sites converted."`

---

## Phase 3 — IndexingQueue + Worker

### Scope

New module: `indexing_queue.py`.

**Work item dataclass:**

```python
@dataclass(frozen=True)
class IndexJob:
    job_type: str          # "directory", "file", "file_deleted", "system_collection"
    path: Path | None      # file or directory path (None for system collections)
    collection_name: str   # target collection name
    indexer_type: str       # "obsidian", "code", "project", "email", "calibre", "rss", "prune"
    force: bool = False
```

**Queue class:**

```python
class IndexingQueue:
    def __init__(self, config: Config, status: IndexingStatus):
        self._queue: queue.Queue[IndexJob | None] = queue.Queue()
        self._config = config
        self._status = status
        self._worker = threading.Thread(target=self._run, name="index-worker", daemon=True)

    def start(self) -> None:
        self._worker.start()

    def submit(self, job: IndexJob) -> None:
        self._queue.put(job)
        self._status.increment(job.collection_name)

    def shutdown(self) -> None:
        self._queue.put(None)  # sentinel
        self._worker.join(timeout=30)

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                break
            try:
                self._process(job)
            except Exception:
                logger.exception("Indexing failed: %s", job)
            finally:
                self._status.decrement(job.collection_name)
```

**`_process()` router**: Single switch/match on `job.indexer_type` that creates the correct indexer. This is the one place where indexer routing lives. No monkey-patching, no inline indexer creation scattered across modules.

**Thread safety by design**: Only the worker thread touches the DB for writes. Submitters only put items on the queue. `queue.Queue` is thread-safe out of the box.

**DocStore thread safety**: Since only the worker thread calls `get_or_convert()`, DocStore is inherently safe. Document this invariant with a comment.

### Process

1. **Worker/coach pairing**: Implement with TDD — red/green/refactor.
2. **Code-simplification agent**: Run twice after implementation.
3. **Architect review**: Verify queue/worker design, confirm single-writer invariant, review `_process()` routing completeness.
4. **Pause**.

### Pause

Compaction directive: `"compact phase 3: indexing queue complete. single queue, single worker, correct indexer routing via _process(). DocStore single-writer invariant documented."`

---

## Phase 4 — Unified Sync Engine + Status

### Scope

**IndexingStatus overhaul** — replace single counter with per-collection file counts:

```python
class IndexingStatus:
    def __init__(self):
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}  # collection_name -> remaining files

    def increment(self, collection: str, count: int = 1) -> None:
        with self._lock:
            self._counts[collection] = self._counts.get(collection, 0) + count

    def decrement(self, collection: str, count: int = 1) -> None:
        with self._lock:
            current = self._counts.get(collection, 0)
            new_val = max(0, current - count)
            if new_val == 0:
                self._counts.pop(collection, None)
            else:
                self._counts[collection] = new_val

    def to_dict(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._counts:
                return None
            return {
                "active": True,
                "total_remaining": sum(self._counts.values()),
                "collections": dict(self._counts),
            }
```

**Sync engine rewrite** (`sync.py`) — `run_startup_sync()` enumerates all sources and submits `IndexJob` items to the queue:

1. **Home directories**: Scan each user dir, call `detect_directory_type()`, submit with correct `indexer_type`.
2. **Global paths**: Same detection and submit.
3. **Obsidian vaults**: From `config.obsidian_vaults`, submit as `indexer_type="obsidian"`.
4. **System collections**: Submit one job each for email, calibre, RSS (if not in `disabled_collections`).

The sync function no longer creates indexers or DB connections. It counts files per collection, calls `status.increment(collection, file_count)`, and submits jobs. The queue worker handles everything else.

**Correct indexer routing**: Lives entirely in `IndexingQueue._process()` (Phase 3). The sync engine just labels each job correctly using `detect_directory_type()`.

### Process

1. **Worker/coach pairing**: Implement with TDD — red/green/refactor.
2. **Code-simplification agent**: Run twice after implementation.
3. **Architect review**: Verify all source types are enumerated, status counting is accurate, no inline indexing remains.
4. **Pause**.

### Pause

Compaction directive: `"compact phase 4: unified sync and status complete. all sources (home, global, obsidian, email, calibre, rss) submit to queue. per-collection file-count tracking in IndexingStatus."`

---

## Phase 5 — Search Optimization

### Scope

**N+1 elimination** — replace per-candidate `_passes_filters()` with a single batch query:

```python
def _batch_load_metadata(conn, doc_ids: list[int]) -> dict[int, Row]:
    placeholders = ",".join("?" * len(doc_ids))
    rows = conn.execute(f"""
        SELECT d.id, d.metadata, d.collection_id, c.name AS coll_name,
               c.collection_type, s.source_type, s.source_path,
               s.file_modified_at
        FROM documents d
        JOIN collections c ON d.collection_id = c.id
        JOIN sources s ON d.source_id = s.id
        WHERE d.id IN ({placeholders})
    """, doc_ids).fetchall()
    return {row["id"]: row for row in rows}
```

One query for all candidates instead of one per candidate. Filter logic runs in-memory against the returned rows.

**N+1 explanation**: The N+1 pattern occurs when code fetches a list of N items, then executes a separate query for each item's related data. In this codebase: vector search returns N candidates (up to `top_k * 50` with filters), then `_passes_filters()` runs 1 JOIN query per candidate. The fix: 2 queries total (candidates + batch metadata load), with filtering in Python.

**Stale detection** — after final top-K results are selected:

```python
for result in top_k_results:
    try:
        st = os.stat(result["source_path"])
        if st.st_mtime > parse_mtime(result["file_modified_at"]):
            result["stale"] = True
    except FileNotFoundError:
        result["stale"] = True
```

Only runs on final results (typically 10). Sub-millisecond. The `file_modified_at` is already available from the batch metadata query.

**Centralized FTS escaping** — new `search_utils.py`:

```python
def escape_fts_query(query: str) -> str:
    """Escape user input for safe use in FTS5 MATCH queries.

    Treats the entire input as a literal search phrase.
    Doubles internal double-quotes and wraps in double quotes
    per SQLite FTS5 spec (section 3.1).

    SQL parameterization prevents injection but does NOT prevent
    FTS syntax abuse within the parameter itself. Both layers are needed.
    """
    escaped = query.replace('"', '""')
    return f'"{escaped}"'
```

Replace the current `_escape_fts_query()` in `search.py` with an import from `search_utils.py`. One call site currently; centralized for future safety.

### Process

1. **Worker/coach pairing**: Implement with TDD — red/green/refactor.
2. **Code-simplification agent**: Run twice after implementation.
3. **Architect review**: Verify N+1 is eliminated (count queries in test), stale detection doesn't add latency, FTS escaping is correct per spec.
4. **Pause**.

### Pause

Compaction directive: `"compact phase 5: search optimization complete. N+1 eliminated via batch metadata load, stat-based stale detection on top-K, FTS escaping centralized per SQLite FTS5 spec."`

---

## Phase 6 — Watcher + System Collection Monitoring

### Scope

**File watcher rewrite** — `DebouncedIndexQueue` stays (debounce + RLock is solid), but callback submits to `IndexingQueue` instead of calling `_index_file()` directly:

```python
def _on_files_changed(files: list[Path], config: Config, queue: IndexingQueue):
    for file_path in files:
        collection = map_file_to_collection(file_path, config)
        indexer_type = detect_indexer_type_for_file(file_path, config)
        if file_path.exists():
            queue.submit(IndexJob(
                job_type="file", path=file_path,
                collection_name=collection, indexer_type=indexer_type,
            ))
        else:
            queue.submit(IndexJob(
                job_type="file_deleted", path=file_path,
                collection_name=collection, indexer_type="prune",
            ))
```

**Correct routing for watched files** — `detect_indexer_type_for_file()` walks up the directory tree to find the nearest `.obsidian` or `.git` marker. Replaces the current bug where everything goes through ProjectIndexer.

**System collection monitoring** — new `SystemCollectionWatcher` class:

```python
class SystemCollectionWatcher:
    def __init__(self, config: Config, queue: IndexingQueue):
        self._db_paths = self._collect_db_paths(config)
        self._debounce = DebouncedIndexQueue(
            callback=self._check_and_submit,
            debounce_seconds=10.0,  # longer debounce for WAL-noisy DB files
        )
```

Watches SQLite database files for email, calibre, RSS. On debounced change, checks watermarks. If new content exists, submits an `IndexJob`. If not, no-op.

**Config file watching** — watch `~/.ragling/config.json`. On change, load a new frozen `Config`, atomically replace the reference, and re-evaluate what needs watching (new vaults, changed paths, etc.).

**Expanded watch scope** — the observer now watches:
- Home directories (existing)
- Global paths (existing)
- Obsidian vault paths (new)
- System collection DB file paths (new)
- Config file (new)

### Process

1. **Worker/coach pairing**: Implement with TDD — red/green/refactor.
2. **Code-simplification agent**: Run twice after implementation.
3. **Architect review**: Verify all source types are watched, correct indexer routing for watched files, debounce timing is appropriate, config reload is atomic.
4. **Pause**.

### Pause

Compaction directive: `"compact phase 6: watcher integration complete. file watcher and system DB monitor both feed IndexingQueue. config file watching with atomic reload. correct indexer routing via directory marker detection."`

---

## Phase 7 — TLS

### Scope

**New module: `tls.py`** — CA generation, server cert issuance, cert path resolution using the `cryptography` library:

```python
def ensure_tls_certs(tls_dir: Path = None) -> TLSConfig:
    """Generate CA + server cert if they don't exist. Return paths."""
    tls_dir = tls_dir or Path.home() / ".ragling" / "tls"
    ca_cert = tls_dir / "ca.pem"
    ca_key = tls_dir / "ca-key.pem"
    server_cert = tls_dir / "server.pem"
    server_key = tls_dir / "server-key.pem"

    if not ca_cert.exists():
        _generate_ca(ca_cert, ca_key)
    if not server_cert.exists():
        _generate_server_cert(server_cert, server_key, ca_cert, ca_key)

    return TLSConfig(ca_cert, ca_key, server_cert, server_key)
```

Certificate details:
- CA: self-signed, valid 10 years.
- Server cert: signed by CA, valid 1 year, auto-regenerated on startup when expired.
- SAN: `localhost` and `127.0.0.1`.
- Key files: `~/.ragling/tls/` with `0o600` permissions on private keys.

File layout:
```
~/.ragling/tls/
    ca.pem          # CA certificate (distribute to clients)
    ca-key.pem      # CA private key (never leaves this dir)
    server.pem      # Server cert signed by CA
    server-key.pem  # Server private key
```

**Server integration** — the `serve` command wraps SSE transport with TLS:

```python
ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_ctx.load_cert_chain(tls.server_cert, tls.server_key)
# Pass ssl_ctx to uvicorn/starlette when starting SSE
```

Stdio transport remains unencrypted (local IPC, no network exposure).

**MCP config CLI command** — `ragling mcp-config` outputs the correct JSON snippet:

```json
{
  "mcpServers": {
    "ragling": {
      "url": "https://localhost:8080/sse",
      "ca_cert": "~/.ragling/tls/ca.pem"
    }
  }
}
```

**External documentation** — NANOCLAW.md should document: mount `~/.ragling/tls/ca.pem` read-only into containers and set `SSL_CERT_FILE` or equivalent trust store path.

### Process

1. **Worker/coach pairing**: Implement with TDD — red/green/refactor.
2. **Code-simplification agent**: Run twice after implementation.
3. **Architect review**: Verify cert generation is correct (SAN, validity, key permissions), TLS context configuration, no plaintext fallback on SSE.
4. **Pause**.

### Pause

Compaction directive: `"compact phase 7: TLS complete. self-signed CA in ~/.ragling/tls/, SSE encrypted, stdio unchanged, mcp-config command outputs config with ca_cert path. NANOCLAW.md documented."`

---

## Cross-Cutting Notes

### Thread Safety Summary

Under the new architecture, thread safety is achieved structurally:

- **IndexingQueue**: Single worker thread processes all write operations. `queue.Queue` is thread-safe. Submitters (sync, watcher, MCP tools) only enqueue.
- **Config**: Frozen dataclass. No mutation possible. Each operation derives its own snapshot via `with_overrides()`.
- **DocStore**: Only accessed by the IndexingQueue worker thread (single-writer invariant). No additional locking needed.
- **DebouncedIndexQueue**: Already uses RLock correctly. Callback now submits to IndexingQueue instead of doing work directly.
- **IndexingStatus**: Lock-protected dict. Increment/decrement are atomic.
- **Search**: Read-only DB access. Multiple concurrent reads are safe under WAL mode.

### Not All MATCH Queries Are FTS

`MATCH` is used in two contexts: FTS5 (`documents_fts MATCH ?` — user text, needs escaping) and sqlite-vec (`vec_documents WHERE embedding MATCH ?` — binary blob, no escaping). The centralized `escape_fts_query()` applies only to the FTS path. Currently one call site; if more appear, add a lint rule.

### Duplicate Prevention in Two-Pass Scans

When a git repo contains document files (`.pdf`, `.docx`), the git indexer handles code and the project indexer handles documents. Each file gets a unique `source_path` per collection. `UNIQUE(collection_id, source_path)` on `sources` and `upsert_source_with_chunks` delete-then-reinsert prevent duplicates. Verified by test, no code change needed.
