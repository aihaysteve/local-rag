# Operational Hardening Plan

Thread safety, sync wiring, search quality, and polish. Addresses all gaps identified by the expert audit of 2026-02-17.

---

## 1. Add `PRAGMA busy_timeout` to all SQLite connections

**Why:** Safety net for concurrent access. Without it, SQLite immediately raises `database is locked` when contention occurs. With it, SQLite retries internally for up to 5 seconds.

### Files

- `src/ragling/db.py` line 38 — add after `PRAGMA journal_mode=WAL`:
  ```python
  conn.execute("PRAGMA busy_timeout=5000")
  ```

- `src/ragling/doc_store.py` line 69 — add after `PRAGMA journal_mode=WAL`:
  ```python
  self._conn.execute("PRAGMA busy_timeout=5000")
  ```

### Tests

- `test_db.py` — assert `PRAGMA busy_timeout` returns 5000 on a new connection.
- `test_doc_store.py` — assert `PRAGMA busy_timeout` returns 5000 on DocStore's internal connection.

### Verification

```bash
uv run pytest tests/test_db.py tests/test_doc_store.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## 2. Route `rag_index` through the IndexingQueue

**Why:** The `rag_index` MCP tool (`mcp_server.py:496-581`) creates its own DB connection and DocStore on the MCP handler thread, racing with the `index-worker` thread. Routing through the queue serializes all writes.

### Changes

**`indexing_queue.py`:**

1. `IndexJob` must support a completion signal and result. Since `IndexJob` is `frozen=True`, add a wrapper or make it non-frozen. Preferred approach — add optional mutable fields:
   - Change `frozen=True` to `frozen=False`, or
   - Add a separate `IndexRequest` wrapper containing `job: IndexJob`, `done: threading.Event`, `result: IndexResult | None`
2. Add `submit_and_wait(job, timeout=300) -> IndexResult` method:
   - Creates a `threading.Event`
   - Attaches it to the job/request
   - Calls `self._queue.put()`
   - Increments status
   - Waits on the event
   - Returns the result
3. In `_run()`, after `_process(job)`, if the job has a `done_event`, set it.
4. Capture the `IndexResult` from `_process()` and store it on the job/request so the caller can read it.

**`mcp_server.py`:**

1. Add `indexing_queue: IndexingQueue | None = None` parameter to `create_server()`.
2. Capture it in the closure alongside `server_config` and `indexing_status`.
3. Refactor `rag_index` to:
   - Build `IndexJob(s)` matching the collection type (same routing logic that currently exists)
   - Call `indexing_queue.submit_and_wait(job)` if queue is available
   - Fall back to direct indexing if queue is None (backwards compatibility for tests)
   - Return the same response dict format

**`cli.py`:**

1. Pass `indexing_queue` to `create_server()` at line 741.

### Tests

- `test_indexing_queue.py` — test `submit_and_wait()` blocks until job completes and returns result.
- `test_mcp_server.py` — test `rag_index` submits through queue when available.
- Test that `rag_index` no longer creates its own `get_connection()` / `DocStore()`.

### Verification

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## 3. File-level IndexingStatus

**Why:** Status currently reports job-level counts (one per directory/vault/library). A single "1 remaining" obsidian job could represent 1,000 files. Status should report file-level progress per collection.

### Changes

**`indexing_status.py`:**

1. Add `_file_counts: dict[str, dict[str, int]]` — tracks `{collection: {"total": N, "processed": N}}`.
2. Add methods:
   ```python
   def set_file_total(self, collection: str, total: int) -> None:
       """Set total files discovered for a collection."""

   def file_processed(self, collection: str, count: int = 1) -> None:
       """Increment processed count for a collection."""
   ```
3. Both methods acquire `self._lock`.
4. Update `to_dict()`:
   ```python
   {
       "active": True,
       "total_remaining": 45,
       "collections": {
           "obsidian": {"total": 100, "processed": 55, "remaining": 45},
           "email": {"total": 30, "processed": 30, "remaining": 0},
       }
   }
   ```
   When file-level data exists, `total_remaining` sums file-level remaining. When not yet reported, falls back to job-level count.

**`indexing_queue.py`:**

1. Pass `self._status` to each indexer constructor in `_process()`.
2. Each `_index_*` method passes `status=self._status` to the indexer.

**Indexers (project.py, obsidian.py, calibre_indexer.py, email_indexer.py, rss_indexer.py, git_indexer.py):**

1. Add `status: IndexingStatus | None = None` parameter to constructors.
2. After discovering files, call `self._status.set_file_total(collection, len(files))`.
3. After processing each file, call `self._status.file_processed(collection)`.
4. Guard all calls with `if self._status:` for backwards compatibility.

### Tests

- `test_indexing_status.py` — test `set_file_total`, `file_processed`, thread safety, `to_dict()` output structure.
- `test_indexing_queue.py` — verify status is passed to indexers.

### Verification

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## 4. Fix stale detection and surface the flag

**Why:** `_mark_stale_results()` (`search.py:221-248`) falsely marks non-file sources as stale (email message IDs, RSS article IDs fail `os.stat()`). The computed `stale` flag is never included in MCP responses or CLI output.

### Changes

**`search.py:221-248` — `_mark_stale_results()`:**

1. Skip `os.stat()` for paths that don't start with `/`. Non-filesystem paths (email message IDs, RSS article IDs, `calibre://`, `git://`) should not be checked:
   ```python
   if not result.source_path.startswith("/"):
       continue
   ```
2. Cache `os.stat()` results by `source_path` to avoid re-statting the same file for multiple chunks from the same source:
   ```python
   stat_cache: dict[str, os.stat_result | None] = {}
   ```

**`mcp_server.py:433-451` — result dict construction:**

1. Add `"stale": r.stale` to the result dict.

**`cli.py:451-484` — CLI search output:**

1. Add `[STALE]` marker next to results where `stale` is True.

### Tests

- `test_search.py` — test non-file paths are NOT marked stale. Test stat caching. Test file-backed stale detection still works.
- `test_mcp_server.py` — test `stale` field appears in search response.

### Verification

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## 5. Fix watcher startup condition

**Why:** `cli.py:728` only starts the file watcher when `config.home or config.global_paths` is set. Configs with only obsidian vaults or code groups get no file watching.

### Changes

**`cli.py:728`:**

Replace:
```python
if config.home or config.global_paths:
```
With:
```python
from ragling.watcher import get_watch_paths
if get_watch_paths(config):
```

This delegates to `get_watch_paths()` (watcher.py:17-48) which already checks home, global_paths, obsidian_vaults, and code_groups. Single source of truth.

### Tests

- `test_cli.py` — test that a config with only `obsidian_vaults` (no home, no global_paths) results in the watcher block executing.

### Verification

```bash
uv run pytest tests/test_cli.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## 6. Wire SystemCollectionWatcher into serve

**Why:** `SystemCollectionWatcher` and `_SystemDbHandler` are fully implemented and unit-tested in `system_watcher.py` but never imported or started by the serve command. Changes to email, calibre, and RSS databases are not detected at runtime.

### Changes

**`system_watcher.py` — add `start_system_watcher()`:**

```python
def start_system_watcher(config: Config, queue: IndexingQueue) -> tuple[Observer, SystemCollectionWatcher]:
    """Start a watchdog observer for system collection databases.

    Returns (observer, watcher) for shutdown cleanup.
    """
    watcher = SystemCollectionWatcher(config, queue)
    handler = _SystemDbHandler(watcher)
    observer = Observer()
    for directory in watcher.get_watch_directories():
        observer.schedule(handler, str(directory), recursive=False)
    observer.start()
    return observer, watcher
```

**`cli.py` serve command — after line 739:**

1. Import `start_system_watcher` from `ragling.system_watcher`.
2. Start after sync completes:
   ```python
   def _start_system_watcher_after_sync():
       sync_done.wait()
       start_system_watcher(config, indexing_queue)

   threading.Thread(
       target=_start_system_watcher_after_sync,
       name="sys-watcher-wait",
       daemon=True,
   ).start()
   ```

### Tests

- `test_system_watcher.py` — test `start_system_watcher()` returns a running observer and watcher.
- Test that modifying a DB file within a watched directory triggers a debounced job submission.

### Verification

```bash
uv run pytest tests/test_system_watcher.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## 7. Wire ConfigWatcher and add shutdown cleanup

**Why:** `ConfigWatcher` is implemented with proper locking but never used. Config edits at runtime have zero effect. Additionally, no watchers or the indexing queue have proper shutdown.

### Changes

**`indexing_queue.py`:**

1. Add `set_config(self, config: Config) -> None` method:
   ```python
   def set_config(self, config: Config) -> None:
       self._config = config
   ```
   This is safe because `_config` is only read by the worker thread during `_process()`, and Python attribute assignment is atomic under the GIL. For extra safety, can use a `threading.Lock`.

**`mcp_server.py`:**

1. Add `config_getter: Callable[[], Config] | None = None` parameter to `create_server()`.
2. Update `_get_config()` to use `config_getter()` when available, falling back to `server_config`.

**`cli.py` serve command:**

1. Create `ConfigWatcher`:
   ```python
   from ragling.config_watcher import ConfigWatcher

   def _handle_reload(new_config: Config) -> None:
       indexing_queue.set_config(new_config)
       logger.info("Config reloaded")

   config_watcher = ConfigWatcher(config, on_reload=_handle_reload)
   ```
2. Set up watchdog observer for config file's parent directory.
3. Pass `config_getter=config_watcher.get_config` to `create_server()`.
4. Add shutdown cleanup — register `atexit`:
   ```python
   import atexit

   def _shutdown():
       indexing_queue.shutdown()
       # Stop observers if they were started

   atexit.register(_shutdown)
   ```

### Tests

- `test_config_watcher.py` — test config reload propagates to queue.
- `test_cli.py` — test shutdown cleanup runs.
- Test `_get_config()` reads from config_watcher when provided.

### Verification

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## 8. Search efficiency improvements

**Why:** When filters are active, `_batch_load_metadata` is called up to 3 times for overlapping ID sets. A missing index slows collection-filtered queries.

### Changes

**`search.py`:**

1. Add `metadata_cache: dict[int, sqlite3.Row] = {}` at the top of `search()`.
2. Pass it through to `_batch_load_metadata` calls in `_vector_search` and `_fts_search`.
3. Update `_batch_load_metadata` to check the cache before querying, and populate it with results:
   ```python
   def _batch_load_metadata(conn, doc_ids, cache=None):
       if cache is not None:
           uncached = [id for id in doc_ids if id not in cache]
           if not uncached:
               return {id: cache[id] for id in doc_ids if id in cache}
           # Query only uncached IDs, merge into cache
       ...
   ```
4. The final metadata load after RRF merge also consults the cache.

**`db.py` — in `init_db()`:**

1. Add:
   ```sql
   CREATE INDEX IF NOT EXISTS idx_documents_collection_id ON documents(collection_id);
   ```

### Tests

- `test_search.py` — verify metadata is loaded once per document ID when filters are active.
- `test_db.py` — verify new index exists after `init_db`.

### Verification

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## 9. Improve `rag_search` docstring

**Why:** Summary line includes implementation details (RRF algorithm). `Returns` section incomplete. `stale` field (added in step 4) undocumented.

### Changes

**`mcp_server.py:301`:**

1. Simplify summary:
   ```python
   """Search personal knowledge across indexed collections."""
   ```
2. Move "hybrid vector + full-text search with RRF" to the body as a brief note.
3. Update `Returns` section to list all fields:
   ```
   Returns:
       Dict with ``results`` list, each containing:
       - title: Document or chunk title
       - content: Matched text content
       - collection: Collection name
       - source_type: Type of source (markdown, pdf, email, code, etc.)
       - source_path: Original file or source path
       - source_uri: Clickable URI to open the original (or null)
       - score: Relevance score (higher is better)
       - metadata: Source-specific metadata dict
       - stale: True if the source has changed since indexing

       When Ollama is unreachable, returns dict with ``error`` key.
       Includes ``indexing_status`` when background indexing is active.
   ```

### Tests

None — docstring only.

### Verification

```bash
uv run ruff check . && uv run ruff format --check .
```

---

## 10. TLS polish

**Why:** Docker containers connecting via `host.docker.internal` get hostname mismatch. `issuer_url` inconsistently says HTTP.

### Changes

**`tls.py:134-138` — `_generate_server_cert()`:**

1. Add `host.docker.internal` to the SAN:
   ```python
   x509.SubjectAlternativeName([
       x509.DNSName("localhost"),
       x509.DNSName("host.docker.internal"),
       x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
   ])
   ```

**`tls.py` — `ensure_tls_certs()`:**

1. After the expired check (line 68), add a near-expiry warning:
   ```python
   elif (cert.not_valid_after_utc - now).days < 30:
       logger.warning("Server certificate expires in %d days", (cert.not_valid_after_utc - now).days)
   ```

**`mcp_server.py:282`:**

1. Change `"http://localhost"` to `"https://localhost"`.

**Documentation note:** Users with existing `~/.ragling/tls/server.*` need to delete those files and restart for the new SAN. Document this in the commit message.

### Tests

- `test_tls.py` — verify `host.docker.internal` in generated cert SANs.
- `test_tls.py` — test near-expiry warning is logged.
- `test_mcp_server.py` — test issuer_url uses HTTPS.

### Verification

```bash
uv run pytest tests/test_tls.py tests/test_mcp_server.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## 11. Remove dead `create_ssl_context()`

**Why:** `tls.py:150-161` — defined and tested but never called. Uvicorn handles SSL context creation internally via the cert/key file paths passed in `cli.py:763-764`.

### Changes

1. Delete `create_ssl_context()` from `tls.py:150-161`.
2. Delete `TestCreateSSLContext` from `test_tls.py`.
3. Remove the `ssl` import from `tls.py` if no longer used.

### Tests

All remaining tests pass.

### Verification

```bash
uv run pytest tests/test_tls.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## 12. Enable ruff S608

**Why:** SQL injection detection rule. Creates an audit trail — all dynamic SQL construction is explicitly marked and reviewed.

### Changes

**`pyproject.toml`:**

1. Add `"S608"` to `ruff.lint.select` (or `extend-select`).

**Flagged files (add `# noqa: S608` with explanation):**

Investigate which lines are flagged and add targeted suppressions. These should all be f-strings constructing table/column names (not user input), e.g.:
```python
f"CREATE VIRTUAL TABLE ... vec0(embedding float[{dim}] ...)"  # noqa: S608 — dim is from config, not user input
```

### Tests

```bash
uv run ruff check .
```

### Verification

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

---

## Final verification

After all 12 steps:

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

### Manual checks

1. Start `ragling serve --sse`, verify TLS handshake succeeds with `host.docker.internal` SAN.
2. Edit `~/.ragling/config.json` while server runs, verify "Config reloaded" in logs.
3. Call `rag_index("obsidian")` via MCP while startup sync is running, verify no `database is locked` errors.
4. Search for an email, verify result is NOT marked `[STALE]`.
5. Modify an indexed file, search for it, verify result IS marked `[STALE]`.
6. Verify `indexing_status` in search responses shows file-level remaining counts.

---

## Summary

| Step | Area | Effort | Impact |
|------|------|--------|--------|
| 1 | busy_timeout | Trivial | Prevents DB locked errors |
| 2 | rag_index → queue | Medium | Eliminates concurrent write race |
| 3 | File-level status | Medium | Accurate progress reporting |
| 4 | Stale detection | Medium | Correct staleness in results |
| 5 | Watcher condition | Trivial | Obsidian-only configs get watching |
| 6 | SystemCollectionWatcher | Medium | Runtime email/calibre/RSS sync |
| 7 | ConfigWatcher + shutdown | Medium-Large | Runtime config reload |
| 8 | Search efficiency | Small | Fewer redundant DB queries |
| 9 | rag_search docstring | Small | Better MCP tool documentation |
| 10 | TLS polish | Small | Docker connectivity + cert warnings |
| 11 | Dead code cleanup | Trivial | Remove unused function |
| 12 | ruff S608 | Small | SQL injection audit trail |
