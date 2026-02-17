# Operational Hardening Design

Validated design for the 12-step operational hardening plan. Addresses thread safety, sync wiring, search quality, TLS polish, and code safety gaps identified during the 2026-02-17 expert audit.

---

## Requirements Traceability

All requirements from the design review mapped to their resolution:

| # | Requirement | Resolution |
|---|---|---|
| 1 | TLS with trusted certificate | Step 10 — polish existing self-signed CA (Docker SAN, near-expiry, HTTPS issuer) |
| 2 | System collection startup sync + monitoring | Step 6 — wire SystemCollectionWatcher into serve |
| 3 | Sync all paths (home, global, obsidian, system) | Step 5 — fix watcher startup condition to delegate to `get_watch_paths()` |
| 4 | Sync creates correct category indexer | Step 2 — rag_index routes through IndexingQueue with correct routing |
| 5 | `_SUPPORTED_EXTENSIONS` / `_EXTENSION_MAP` purpose | **Already resolved** — `_SUPPORTED_EXTENSIONS` deleted in overhaul; `_EXTENSION_MAP` is sole source of truth with `is_supported_extension()` helper |
| 6 | Two-pass scan duplicate prevention | **Already resolved** — `test_base.py:239` verifies `test_two_pass_indexing_no_duplicates`; UNIQUE constraint + upsert prevents duplicates |
| 7 | Indexing status tracks file count | Step 3 — replace job-level with file-level counting |
| 8 | Report file count remaining per collection | Step 3 — `to_dict()` output includes per-collection remaining |
| 9 | Thread safety of indexing | Steps 1–2 — busy_timeout safety net + single-writer via queue |
| 10 | Stale entries at search time | Step 4 — fix false positives for non-file sources, surface flag in responses |
| 11 | Search efficiency optimization | Step 8 — metadata cache + collection_id index |
| 12 | N+1 query pattern | **Already resolved** — `_batch_load_metadata()` in search.py eliminates N+1; explanation in cohesive overhaul design doc |
| 13 | Query escaping correctness | Step 12 — enable ruff S608 for static analysis; `escape_fts_query()` already centralized |
| 14 | Config thread safety | Step 7 — ConfigWatcher wiring; Config already frozen dataclass |
| 15 | Config mutation reconciliation | Step 7 — new frozen Config propagates to queue and MCP server atomically |
| 16 | DocStore / debounce queue thread safety | Steps 1–2 — busy_timeout for DocStore; single-writer invariant for IndexingQueue |
| 17 | Hash function consolidation | **Already resolved** — `doc_store.py` imports `file_hash` from `base.py`; other `hashlib.sha256` uses serve different purposes (config hash, message ID, description content) |
| 18 | `rag_search` docstring improvements | Step 9 — Pythonic rewrite with complete Returns section |
| 19 | mypy/ruff static escaping checks | **Covered by Step 12** — mypy has no SQL injection rules; ruff S608 (bandit) is the correct tool |

---

## Architectural Decisions (Unchanged)

These decisions from the cohesive overhaul remain in force:

- **Single IndexingQueue + single worker thread**: All writes serialized. Ollama is the bottleneck, not DB writes.
- **Self-signed CA for TLS**: Isolated to `~/.ragling/tls/`. No system keychain modification.
- **Frozen Config**: Immutable dataclass with `with_overrides()`. Thread-safe by construction.
- **FTS5 escaping**: Double internal quotes, wrap in double quotes per SQLite FTS5 spec section 3.1.

---

## Implementation Plan

### Step 1: Add `PRAGMA busy_timeout` to all SQLite connections

**Risk:** Low | **Effort:** Trivial

Safety net for concurrent access. Without it, SQLite immediately raises `database is locked` under contention. With it, SQLite retries internally for up to 5 seconds.

**Files:**
- `src/ragling/db.py` — add after `PRAGMA journal_mode=WAL`: `conn.execute("PRAGMA busy_timeout=5000")`
- `src/ragling/doc_store.py` — add after `PRAGMA journal_mode=WAL`: `self._conn.execute("PRAGMA busy_timeout=5000")`

**Tests:**
- `test_db.py` — assert `PRAGMA busy_timeout` returns 5000 on a new connection
- `test_doc_store.py` — assert `PRAGMA busy_timeout` returns 5000 on DocStore's internal connection

**Verification:** `uv run pytest tests/test_db.py tests/test_doc_store.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

### Step 2: Route `rag_index` through the IndexingQueue

**Risk:** High | **Effort:** Medium

The `rag_index` MCP tool creates its own DB connection and DocStore on the MCP handler thread, racing with the index-worker thread. Routing through the queue serializes all writes.

**Design choice:** Use an `IndexRequest` wrapper rather than making `IndexJob` non-frozen. This keeps `IndexJob` immutable and separates the completion signal concern:

```python
@dataclass
class IndexRequest:
    job: IndexJob
    done: threading.Event = field(default_factory=threading.Event)
    result: IndexResult | None = None
```

**Changes:**

`indexing_queue.py`:
1. Add `IndexRequest` wrapper with `done: threading.Event` and `result: IndexResult | None`
2. Add `submit_and_wait(job, timeout=300) -> IndexResult` method
3. In `_run()`, after `_process(job)`, set `done_event` and store result

`mcp_server.py`:
1. Add `indexing_queue: IndexingQueue | None = None` to `create_server()`
2. Refactor `rag_index` to build `IndexJob(s)` and call `submit_and_wait()`
3. Fall back to direct indexing when queue is None (tests / stdio)

`cli.py`:
1. Pass `indexing_queue` to `create_server()`

**Tests:**
- `test_indexing_queue.py` — `submit_and_wait()` blocks until job completes and returns result
- `test_mcp_server.py` — `rag_index` submits through queue when available
- Verify `rag_index` no longer creates its own `get_connection()` / `DocStore()`

**Verification:** `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

### Step 3: File-level IndexingStatus

**Risk:** Medium | **Effort:** Medium

Status currently reports job-level counts. A single "1 remaining" obsidian job could represent 1,000 files. Status should report file-level progress per collection.

**Changes:**

`indexing_status.py`:
1. Add `_file_counts: dict[str, dict[str, int]]` tracking `{collection: {"total": N, "processed": N}}`
2. Add `set_file_total(collection, total)` and `file_processed(collection, count=1)` (lock-protected)
3. Update `to_dict()`:
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
   Falls back to job-level count when file-level data not yet reported.

`indexing_queue.py`:
1. Pass `self._status` to each indexer constructor in `_process()`

**Indexers** (project, obsidian, calibre, email, rss, git):
1. Add `status: IndexingStatus | None = None` parameter
2. After discovering files: `self._status.set_file_total(collection, len(files))`
3. After processing each file: `self._status.file_processed(collection)`
4. Guard with `if self._status:` for backwards compatibility

**Tests:**
- `test_indexing_status.py` — file-level methods, thread safety, `to_dict()` shape
- `test_indexing_queue.py` — status passed to indexers

**Verification:** `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

### Step 4: Fix stale detection and surface the flag

**Risk:** Medium | **Effort:** Medium

`_mark_stale_results()` falsely marks non-file sources as stale (email message IDs, RSS article IDs fail `os.stat()`). The computed `stale` flag is never included in MCP responses.

**Changes:**

`search.py` (`_mark_stale_results()`):
1. Skip `os.stat()` for paths that don't start with `/`:
   ```python
   if not result.source_path.startswith("/"):
       continue
   ```
2. Cache `os.stat()` results by `source_path` to avoid re-statting multi-chunk files

`mcp_server.py`:
1. Add `"stale": r.stale` to the result dict

`cli.py`:
1. Add `[STALE]` marker next to stale results

**Tests:**
- `test_search.py` — non-file paths NOT marked stale; stat caching; file-backed stale detection works
- `test_mcp_server.py` — `stale` field appears in search response

**Verification:** `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

### Step 5: Fix watcher startup condition

**Risk:** Low | **Effort:** Trivial

`cli.py` only starts the file watcher when `config.home or config.global_paths` is set. Configs with only obsidian vaults or code groups get no file watching.

**Change:**

Replace:
```python
if config.home or config.global_paths:
```
With:
```python
from ragling.watcher import get_watch_paths
if get_watch_paths(config):
```

This delegates to `get_watch_paths()` which already checks home, global_paths, obsidian_vaults, and code_groups.

**Tests:** `test_cli.py` — config with only `obsidian_vaults` gets watching

**Verification:** `uv run pytest tests/test_cli.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

### Step 6: Wire SystemCollectionWatcher into serve

**Risk:** Medium | **Effort:** Medium

`SystemCollectionWatcher` and `_SystemDbHandler` are implemented and unit-tested but never started. Changes to email, calibre, and RSS databases are not detected at runtime.

**Changes:**

`system_watcher.py`:
1. Add `start_system_watcher(config, queue) -> tuple[Observer, SystemCollectionWatcher]` convenience function

`cli.py`:
1. Import `start_system_watcher`
2. Start after sync completes:
   ```python
   def _start_system_watcher_after_sync():
       sync_done.wait()
       start_system_watcher(config, indexing_queue)

   threading.Thread(target=_start_system_watcher_after_sync, name="sys-watcher-wait", daemon=True).start()
   ```

**Dependency:** Step 5 should be done first (watcher condition fix).

**Tests:**
- `test_system_watcher.py` — `start_system_watcher()` returns running observer and watcher
- Modifying a DB file triggers debounced job submission

**Verification:** `uv run pytest tests/test_system_watcher.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

### Step 7: Wire ConfigWatcher and add shutdown cleanup

**Risk:** Medium-Large | **Effort:** Medium-Large

`ConfigWatcher` is implemented with proper locking but never used. Config edits at runtime have zero effect. No watchers or the indexing queue have proper shutdown.

**Changes:**

`indexing_queue.py`:
1. Add `set_config(config)` — replaces `_config`. Safe under GIL (atomic attribute assignment). No additional Lock needed.

`mcp_server.py`:
1. Add `config_getter: Callable[[], Config] | None` to `create_server()`
2. Update `_get_config()` to call `config_getter()` when available

`cli.py`:
1. Create `ConfigWatcher` with `on_reload` callback that calls `indexing_queue.set_config(new_config)`
2. Set up watchdog observer for config file
3. Pass `config_getter=config_watcher.get_config` to `create_server()`
4. Add `atexit` shutdown:
   ```python
   def _shutdown():
       indexing_queue.shutdown()
       # Stop observers
   atexit.register(_shutdown)
   ```

**Config mutation reconciliation:** When config changes at runtime:
- New frozen Config replaces the old one atomically
- IndexingQueue worker picks up the new config on next job
- MCP tool calls get latest config via `config_getter()`
- No in-flight operations are affected (they hold their own config snapshot)

**Dependency:** Step 6 should be done first (shutdown covers both system watcher and file watcher).

**Tests:**
- `test_config_watcher.py` — config reload propagates to queue
- `test_cli.py` — shutdown cleanup runs
- `_get_config()` uses config_watcher when provided

**Verification:** `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

### Step 8: Search efficiency improvements

**Risk:** Low | **Effort:** Small

When filters are active, `_batch_load_metadata` is called up to 3 times for overlapping ID sets. A missing index slows collection-filtered queries.

**Changes:**

`search.py`:
1. Add `metadata_cache: dict[int, sqlite3.Row] = {}` at the top of `search()`
2. Pass through to all `_batch_load_metadata` calls
3. `_batch_load_metadata` checks cache first, queries only uncached IDs, merges results

`db.py`:
1. Add: `CREATE INDEX IF NOT EXISTS idx_documents_collection_id ON documents(collection_id);`

**Tests:**
- `test_search.py` — metadata loaded once per document ID with filters
- `test_db.py` — new index exists after `init_db`

**Verification:** `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

### Step 9: Improve `rag_search` docstring

**Risk:** Low | **Effort:** Small

Summary line includes implementation details. `Returns` section incomplete. `stale` field undocumented.

**Changes:**

`mcp_server.py`:
1. Simplify summary: `"""Search personal knowledge across indexed collections."""`
2. Move RRF details to body
3. Complete `Returns` section listing all fields including `stale`

**Dependency:** Step 4 (stale field added to responses).

**Verification:** `uv run ruff check . && uv run ruff format --check .`

---

### Step 10: TLS polish

**Risk:** Low | **Effort:** Small

Docker containers get hostname mismatch. `issuer_url` inconsistently says HTTP. No near-expiry warning.

**Changes:**

`tls.py` (`_generate_server_cert()`):
1. Add `host.docker.internal` to SAN:
   ```python
   x509.SubjectAlternativeName([
       x509.DNSName("localhost"),
       x509.DNSName("host.docker.internal"),
       x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
   ])
   ```
2. Add 30-day near-expiry warning after the expired check

`mcp_server.py`:
1. Change `"http://localhost"` to `"https://localhost"`

**Migration:** Users with existing `~/.ragling/tls/server.*` must delete those files and restart for the new SAN.

**Tests:**
- `test_tls.py` — `host.docker.internal` in generated cert SANs; near-expiry warning logged
- `test_mcp_server.py` — issuer_url uses HTTPS

**Verification:** `uv run pytest tests/test_tls.py tests/test_mcp_server.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

### Step 11: Remove dead `create_ssl_context()`

**Risk:** Low | **Effort:** Trivial

Defined and tested but never called. Uvicorn handles SSL context creation internally.

**Changes:**
1. Delete `create_ssl_context()` from `tls.py`
2. Delete `TestCreateSSLContext` from `test_tls.py`
3. Remove `ssl` import from `tls.py` if no longer used

**Dependency:** Step 10 (verify `ssl` import usage after TLS changes).

**Verification:** `uv run pytest tests/test_tls.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

### Step 12: Enable ruff S608

**Risk:** Low | **Effort:** Small

SQL injection detection rule. Creates an audit trail for all dynamic SQL construction.

**Changes:**

`pyproject.toml`:
1. Add `"S608"` to ruff lint select

Flagged files:
1. Investigate which lines are flagged
2. Add targeted `# noqa: S608` with explanations (e.g., "dim is from config, not user input")

**Note:** mypy has no SQL injection detection capability. S608 (bandit) is the appropriate static analysis tool for this concern. The centralized `escape_fts_query()` in `search_utils.py` handles the FTS escaping path. sqlite-vec `MATCH` uses binary blobs, not text — no escaping needed.

**Dependency:** Do last — other steps may introduce new dynamic SQL that S608 should catch.

**Verification:** `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`

---

## Step Dependencies

```
Step 1  ← no deps
Step 2  ← no deps
Step 3  ← no deps
Step 4  ← no deps
Step 5  ← no deps
Step 6  ← after Step 5
Step 7  ← after Step 6
Step 8  ← no deps
Step 9  ← after Step 4
Step 10 ← no deps
Step 11 ← after Step 10
Step 12 ← last (catches new dynamic SQL from other steps)
```

Sequential execution (1 through 12) respects all dependencies.

---

## Final Verification

After all 12 steps:

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

### Manual checks

1. Start `ragling serve --sse`, verify TLS handshake succeeds with `host.docker.internal` SAN
2. Edit `~/.ragling/config.json` while server runs, verify "Config reloaded" in logs
3. Call `rag_index("obsidian")` via MCP while startup sync is running, verify no `database is locked` errors
4. Search for an email, verify result is NOT marked `[STALE]`
5. Modify an indexed file, search for it, verify result IS marked `[STALE]`
6. Verify `indexing_status` in search responses shows file-level remaining counts

---

## Risk Summary

| Step | Risk | Mitigation |
|------|------|------------|
| 1 | Low | Two-line change, isolated |
| 2 | **High** | Changes MCP tool data flow; thorough queue integration tests |
| 3 | Medium | Multi-file; file-level status with fallback preserves backwards compat |
| 4 | Medium | Stale detection logic change; test all source path types |
| 5 | Low | One-line delegation |
| 6 | Medium | New runtime watcher; sequenced after sync |
| 7 | **Medium-Large** | Config propagation across threads; frozen Config makes mutation impossible |
| 8 | Low | Request-scoped cache, schema-only index |
| 9 | Low | Docstring only |
| 10 | Low | Cert generation change; migration documented |
| 11 | Low | Dead code removal |
| 12 | Low | Lint rule + annotations |
