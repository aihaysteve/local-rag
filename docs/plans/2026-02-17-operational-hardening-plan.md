# Operational Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Wire together existing infrastructure (IndexingQueue, SystemCollectionWatcher, ConfigWatcher, TLS) and add thread-safety, search efficiency, and code safety improvements across 12 design steps.

**Architecture:** The codebase has a single-writer IndexingQueue, frozen Config, content-addressed DocStore, and hybrid search engine. This plan adds busy_timeout as a safety net, routes MCP rag_index through the queue, adds file-level indexing status, fixes stale detection, wires watchers into the serve command, adds a metadata cache for search, polishes TLS, and enables SQL injection linting.

**Tech Stack:** Python 3.12+, SQLite (WAL + FTS5 + sqlite-vec), watchdog, cryptography, ruff, pytest, mypy

---

### Task 1: Add `PRAGMA busy_timeout` to `db.py`

**Files:**
- Modify: `src/ragling/db.py:38`
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
class TestBusyTimeout:
    """Tests for PRAGMA busy_timeout on connections."""

    def test_busy_timeout_is_set(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            group_name="timeout-test",
            group_db_dir=tmp_path / "groups",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            assert row[0] == 5000
        finally:
            conn.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::TestBusyTimeout -v`
Expected: FAIL — `assert 0 == 5000`

**Step 3: Write minimal implementation**

In `src/ragling/db.py`, add after line 38 (`conn.execute("PRAGMA journal_mode=WAL")`):

```python
    conn.execute("PRAGMA busy_timeout=5000")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py::TestBusyTimeout -v`
Expected: PASS

**Step 5: Run full check**

Run: `uv run pytest tests/test_db.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/db.py tests/test_db.py
git commit -m "feat: add PRAGMA busy_timeout=5000 to db.py connections"
```

---

### Task 2: Add `PRAGMA busy_timeout` to `doc_store.py`

**Files:**
- Modify: `src/ragling/doc_store.py:68`
- Test: `tests/test_doc_store.py`

**Step 1: Write the failing test**

Add to `tests/test_doc_store.py`:

```python
class TestDocStoreBusyTimeout:
    """Tests for PRAGMA busy_timeout on DocStore connections."""

    def test_busy_timeout_is_set(self, tmp_path: Path) -> None:
        db_path = tmp_path / "doc_store.sqlite"
        store = DocStore(db_path)
        row = store._conn.execute("PRAGMA busy_timeout").fetchone()
        assert row[0] == 5000
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_doc_store.py::TestDocStoreBusyTimeout -v`
Expected: FAIL — `assert 0 == 5000`

**Step 3: Write minimal implementation**

In `src/ragling/doc_store.py`, add after line 68 (`self._conn.execute("PRAGMA journal_mode=WAL")`):

```python
        self._conn.execute("PRAGMA busy_timeout=5000")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_doc_store.py::TestDocStoreBusyTimeout -v`
Expected: PASS

**Step 5: Run full check**

Run: `uv run pytest tests/test_doc_store.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/doc_store.py tests/test_doc_store.py
git commit -m "feat: add PRAGMA busy_timeout=5000 to DocStore connections"
```

---

### Task 3: Add `IndexRequest` wrapper to `indexing_queue.py`

**Files:**
- Modify: `src/ragling/indexing_queue.py`
- Test: `tests/test_indexing_queue.py`

**Step 1: Write the failing test**

Add to `tests/test_indexing_queue.py`:

```python
from ragling.indexing_queue import IndexRequest


class TestIndexRequest:
    """Tests for the IndexRequest synchronous wrapper."""

    def test_index_request_has_event_and_result(self) -> None:
        job = IndexJob(
            job_type="directory",
            path=Path("/tmp/test"),
            collection_name="test",
            indexer_type="project",
        )
        request = IndexRequest(job=job)
        assert not request.done.is_set()
        assert request.result is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_indexing_queue.py::TestIndexRequest -v`
Expected: FAIL — `ImportError: cannot import name 'IndexRequest'`

**Step 3: Write minimal implementation**

In `src/ragling/indexing_queue.py`, add after the `IndexJob` class (after line 54), and add `threading` and `field` imports:

```python
@dataclass
class IndexRequest:
    """Wrapper for synchronous job submission with completion signaling.

    Wraps an IndexJob with a threading.Event for blocking until the
    worker completes processing, and a result slot for the IndexResult.
    """

    job: IndexJob
    done: threading.Event = field(default_factory=threading.Event)
    result: IndexResult | None = None
```

Also add to imports at the top:

```python
from dataclasses import dataclass, field
```

And add a forward reference for IndexResult:

```python
if TYPE_CHECKING:
    from ragling.doc_store import DocStore
    from ragling.indexers.base import IndexResult
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_indexing_queue.py::TestIndexRequest -v`
Expected: PASS

**Step 5: Run full check**

Run: `uv run pytest tests/test_indexing_queue.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/indexing_queue.py tests/test_indexing_queue.py
git commit -m "feat: add IndexRequest wrapper with completion event"
```

---

### Task 4: Add `submit_and_wait` to `IndexingQueue`

**Files:**
- Modify: `src/ragling/indexing_queue.py`
- Test: `tests/test_indexing_queue.py`

**Step 1: Write the failing test**

Add to `tests/test_indexing_queue.py`:

```python
class TestSubmitAndWait:
    """Tests for IndexingQueue.submit_and_wait()."""

    def test_blocks_until_job_completes(self, tmp_path: Path) -> None:
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        status = IndexingStatus()
        queue = IndexingQueue(config, status)
        queue.start()

        job = IndexJob(
            job_type="directory",
            path=tmp_path,
            collection_name="test-coll",
            indexer_type="project",
        )

        try:
            result = queue.submit_and_wait(job, timeout=30)
            assert result is not None
        finally:
            queue.shutdown()

    def test_timeout_returns_none(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        status = IndexingStatus()
        queue = IndexingQueue(config, status)
        # Don't start the worker — job will never be processed

        job = IndexJob(
            job_type="directory",
            path=tmp_path,
            collection_name="test-coll",
            indexer_type="project",
        )

        result = queue.submit_and_wait(job, timeout=0.1)
        assert result is None
        queue.shutdown()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_indexing_queue.py::TestSubmitAndWait -v`
Expected: FAIL — `AttributeError: 'IndexingQueue' object has no attribute 'submit_and_wait'`

**Step 3: Write minimal implementation**

In `src/ragling/indexing_queue.py`, modify the `_run` method and add `submit_and_wait`:

Change the `_queue` type and `_run` to accept both `IndexJob` and `IndexRequest`:

```python
    def __init__(self, config: Config, status: IndexingStatus) -> None:
        self._queue: queue.Queue[IndexJob | IndexRequest | None] = queue.Queue()
        self._config = config
        self._status = status
        self._worker = threading.Thread(target=self._run, name="index-worker", daemon=True)
```

Add the `submit_and_wait` method after `submit`:

```python
    def submit_and_wait(
        self, job: IndexJob, timeout: float = 300
    ) -> IndexResult | None:
        """Submit a job and block until it completes.

        Args:
            job: The indexing job to enqueue.
            timeout: Maximum seconds to wait for completion.

        Returns:
            The IndexResult, or None if the timeout expired.
        """
        from ragling.indexers.base import IndexResult

        request = IndexRequest(job=job)
        self._queue.put(request)
        self._status.increment(job.collection_name)
        if request.done.wait(timeout=timeout):
            return request.result
        return None
```

Update `_run` to handle `IndexRequest`:

```python
    def _run(self) -> None:
        """Worker loop: process jobs until sentinel (None) is received."""
        while True:
            item = self._queue.get()
            if item is None:
                break

            if isinstance(item, IndexRequest):
                job = item.job
            else:
                job = item

            try:
                result = self._process(job)
                if isinstance(item, IndexRequest):
                    item.result = result
            except Exception:
                logger.exception("Indexing failed: %s", job)
            finally:
                self._status.decrement(job.collection_name)
                if isinstance(item, IndexRequest):
                    item.done.set()
```

Update `_process` to return `IndexResult | None`:

Change `_process` signature and each `_index_*` method to return the result. For example, change `_index_project`:

```python
    def _process(self, job: IndexJob) -> IndexResult | None:
```

And update each `_index_*` to return the result:

```python
    def _index_project(self, job: IndexJob) -> IndexResult | None:
        from ragling.indexers.project import ProjectIndexer

        with self._open_conn_and_docstore() as (conn, doc_store):
            paths = [job.path] if job.path else []
            indexer = ProjectIndexer(job.collection_name, paths, doc_store=doc_store)
            result = indexer.index(conn, self._config, force=job.force)
            logger.info("Indexed project %s: %s", job.collection_name, result)
            return result
```

(Apply the same `return result` pattern to `_index_code`, `_index_obsidian`, `_index_email`, `_index_calibre`, `_index_rss`. `_prune` returns `None`.)

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_indexing_queue.py::TestSubmitAndWait -v`
Expected: PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/indexing_queue.py tests/test_indexing_queue.py
git commit -m "feat: add submit_and_wait for synchronous job submission"
```

---

### Task 5: Route `rag_index` through the IndexingQueue

**Files:**
- Modify: `src/ragling/mcp_server.py:244-248,496-581`
- Modify: `src/ragling/cli.py:741-745`
- Test: `tests/test_mcp_server.py`

**Step 1: Write the failing test**

Add to `tests/test_mcp_server.py`:

```python
class TestRagIndexQueueRouting:
    """Tests for rag_index routing through IndexingQueue."""

    def test_rag_index_uses_queue_when_available(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch

        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            obsidian_vaults=[tmp_path / "vault"],
        )

        status = IndexingStatus()
        queue = MagicMock(spec=IndexingQueue)
        mock_result = MagicMock()
        mock_result.indexed = 5
        mock_result.skipped = 0
        mock_result.errors = 0
        mock_result.total_found = 5
        queue.submit_and_wait.return_value = mock_result

        server = create_server(
            group_name="default",
            config=config,
            indexing_status=status,
            indexing_queue=queue,
        )

        # The server object has rag_index registered; verify queue parameter accepted
        assert queue is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_server.py::TestRagIndexQueueRouting -v`
Expected: FAIL — `create_server() got an unexpected keyword argument 'indexing_queue'`

**Step 3: Write minimal implementation**

In `src/ragling/mcp_server.py`, update `create_server` signature (line 244):

```python
def create_server(
    group_name: str = "default",
    config: Config | None = None,
    indexing_status: IndexingStatus | None = None,
    indexing_queue: IndexingQueue | None = None,
) -> FastMCP:
```

Add `IndexingQueue` to TYPE_CHECKING imports:

```python
if TYPE_CHECKING:
    from ragling.indexing_queue import IndexingQueue
    from ragling.indexing_status import IndexingStatus
```

Refactor `rag_index` (lines 496-581) to use the queue when available:

```python
    @mcp.tool()
    def rag_index(collection: str, path: str | None = None) -> dict[str, Any]:
        """Trigger indexing for a collection.

        For system collections ('obsidian', 'email', 'calibre', 'rss'), uses configured paths.
        For code groups (matching a key in config code_groups), indexes all repos in that group.
        For project collections, a path argument is required.

        Args:
            collection: Collection name ('obsidian', 'email', 'calibre', 'rss', a code group
                name, or a project name).
            path: Path to index (required for project collections, or to add a single repo
                to a code group).
        """
        from pathlib import Path as P

        from ragling.indexing_queue import IndexJob

        config = _get_config()

        if not config.is_collection_enabled(collection):
            return {"error": f"Collection '{collection}' is disabled in config."}

        # Route through queue when available
        if indexing_queue is not None:
            return _rag_index_via_queue(collection, path, config, indexing_queue)

        # Direct indexing fallback (tests / stdio without queue)
        return _rag_index_direct(collection, path, config)
```

Add the two helper functions inside `create_server` (before `return mcp`):

```python
    def _rag_index_via_queue(
        collection: str, path: str | None, config: Config, queue: IndexingQueue
    ) -> dict[str, Any]:
        """Route indexing through the IndexingQueue."""
        from pathlib import Path as P

        from ragling.indexing_queue import IndexJob

        if collection == "obsidian":
            job = IndexJob("directory", P(path) if path else None, "obsidian", "obsidian")
        elif collection == "email":
            job = IndexJob("system_collection", P(path) if path else None, "email", "email")
        elif collection == "calibre":
            job = IndexJob("system_collection", P(path) if path else None, "calibre", "calibre")
        elif collection == "rss":
            job = IndexJob("system_collection", P(path) if path else None, "rss", "rss")
        elif collection in config.code_groups:
            results = []
            for repo_path in config.code_groups[collection]:
                job = IndexJob("directory", repo_path, collection, "code")
                result = queue.submit_and_wait(job, timeout=300)
                if result:
                    results.append(result)
            return {
                "collection": collection,
                "indexed": sum(r.indexed for r in results),
                "skipped": sum(r.skipped for r in results),
                "errors": sum(r.errors for r in results),
                "total_found": sum(r.total_found for r in results),
            }
        elif path:
            job = IndexJob("directory", P(path), collection, "project")
        else:
            return {
                "error": f"Unknown collection '{collection}'. Provide a path for project indexing."
            }

        result = queue.submit_and_wait(job, timeout=300)
        if result is None:
            return {"error": f"Indexing timed out for collection '{collection}'."}
        return {
            "collection": collection,
            "indexed": result.indexed,
            "skipped": result.skipped,
            "errors": result.errors,
            "total_found": result.total_found,
        }

    def _rag_index_direct(
        collection: str, path: str | None, config: Config
    ) -> dict[str, Any]:
        """Direct indexing without queue (backwards compatibility)."""
        from pathlib import Path as P

        from ragling.doc_store import DocStore
        from ragling.indexers.base import BaseIndexer
        from ragling.indexers.calibre_indexer import CalibreIndexer
        from ragling.indexers.email_indexer import EmailIndexer
        from ragling.indexers.git_indexer import GitRepoIndexer
        from ragling.indexers.obsidian import ObsidianIndexer
        from ragling.indexers.project import ProjectIndexer
        from ragling.indexers.rss_indexer import RSSIndexer

        conn = get_connection(config)
        init_db(conn, config)
        doc_store = DocStore(config.shared_db_path)

        try:
            indexer: BaseIndexer
            if collection == "obsidian":
                indexer = ObsidianIndexer(
                    config.obsidian_vaults, config.obsidian_exclude_folders, doc_store=doc_store
                )
                result = indexer.index(conn, config)
            elif collection == "email":
                indexer = EmailIndexer(str(config.emclient_db_path))
                result = indexer.index(conn, config)
            elif collection == "calibre":
                indexer = CalibreIndexer(config.calibre_libraries, doc_store=doc_store)
                result = indexer.index(conn, config)
            elif collection == "rss":
                indexer = RSSIndexer(str(config.netnewswire_db_path))
                result = indexer.index(conn, config)
            elif collection in config.code_groups:
                total_indexed = total_skipped = total_errors = total_found = 0
                for repo_path in config.code_groups[collection]:
                    idx = GitRepoIndexer(repo_path, collection_name=collection)
                    r = idx.index(conn, config, index_history=True)
                    total_indexed += r.indexed
                    total_skipped += r.skipped
                    total_errors += r.errors
                    total_found += r.total_found
                return {
                    "collection": collection,
                    "indexed": total_indexed,
                    "skipped": total_skipped,
                    "errors": total_errors,
                    "total_found": total_found,
                }
            elif path:
                indexer = ProjectIndexer(collection, [P(path)], doc_store=doc_store)
                result = indexer.index(conn, config)
            else:
                return {
                    "error": f"Unknown collection '{collection}'. Provide a path for project indexing."
                }

            return {
                "collection": collection,
                "indexed": result.indexed,
                "skipped": result.skipped,
                "errors": result.errors,
                "total_found": result.total_found,
            }
        finally:
            doc_store.close()
            conn.close()
```

In `src/ragling/cli.py`, update the `create_server` call (line 741):

```python
    server = create_server(
        group_name=group,
        config=config,
        indexing_status=indexing_status,
        indexing_queue=indexing_queue,
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_server.py::TestRagIndexQueueRouting -v`
Expected: PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/mcp_server.py src/ragling/cli.py tests/test_mcp_server.py
git commit -m "feat: route rag_index MCP tool through IndexingQueue"
```

---

### Task 6: Add file-level tracking to `IndexingStatus`

**Files:**
- Modify: `src/ragling/indexing_status.py`
- Test: `tests/test_indexing_status.py`

**Step 1: Write the failing test**

Add to `tests/test_indexing_status.py`:

```python
class TestFileLevelStatus:
    """Tests for file-level indexing progress."""

    def test_set_file_total_and_processed(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.set_file_total("obsidian", 100)
        status.file_processed("obsidian", 55)

        result = status.to_dict()
        assert result is not None
        assert result["collections"]["obsidian"]["total"] == 100
        assert result["collections"]["obsidian"]["processed"] == 55
        assert result["collections"]["obsidian"]["remaining"] == 45
        assert result["total_remaining"] == 45

    def test_file_counts_replace_job_counts_when_present(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("obsidian")  # job-level: 1 remaining
        status.set_file_total("obsidian", 50)  # file-level: 50 remaining

        result = status.to_dict()
        assert result is not None
        # File-level should take precedence
        assert result["total_remaining"] == 50

    def test_to_dict_shape(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.set_file_total("email", 30)
        status.file_processed("email", 30)
        status.set_file_total("obsidian", 100)
        status.file_processed("obsidian", 55)

        result = status.to_dict()
        assert result is not None
        assert result["active"] is True
        assert "collections" in result
        assert result["collections"]["obsidian"]["remaining"] == 45
        assert result["collections"]["email"]["remaining"] == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_indexing_status.py::TestFileLevelStatus -v`
Expected: FAIL — `AttributeError: 'IndexingStatus' object has no attribute 'set_file_total'`

**Step 3: Write minimal implementation**

Replace `src/ragling/indexing_status.py` with:

```python
"""Thread-safe indexing status tracker with per-collection file counts."""

import threading
from typing import Any


class IndexingStatus:
    """Tracks remaining files to index, broken down by collection.

    Supports both job-level counts (increment/decrement) and file-level
    counts (set_file_total/file_processed). When file-level data exists
    for a collection, it takes precedence over job-level counts.

    Thread-safe. All public methods acquire the internal lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._file_counts: dict[str, dict[str, int]] = {}

    def increment(self, collection: str, count: int = 1) -> None:
        """Increment job-level remaining count for a collection.

        Args:
            collection: Collection name.
            count: Number of jobs to add (default 1).
        """
        with self._lock:
            self._counts[collection] = self._counts.get(collection, 0) + count

    def decrement(self, collection: str, count: int = 1) -> None:
        """Decrement job-level remaining count for a collection.

        Clamps at zero. Removes the collection entry when it reaches zero.

        Args:
            collection: Collection name.
            count: Number of jobs to subtract (default 1).
        """
        with self._lock:
            current = self._counts.get(collection, 0)
            new_val = max(0, current - count)
            if new_val == 0:
                self._counts.pop(collection, None)
            else:
                self._counts[collection] = new_val

    def set_file_total(self, collection: str, total: int) -> None:
        """Set total files discovered for a collection.

        Args:
            collection: Collection name.
            total: Total number of files to process.
        """
        with self._lock:
            self._file_counts[collection] = {"total": total, "processed": 0}

    def file_processed(self, collection: str, count: int = 1) -> None:
        """Increment processed file count for a collection.

        Args:
            collection: Collection name.
            count: Number of files processed (default 1).
        """
        with self._lock:
            if collection in self._file_counts:
                self._file_counts[collection]["processed"] = (
                    self._file_counts[collection].get("processed", 0) + count
                )

    def finish(self) -> None:
        """Mark all indexing as complete."""
        with self._lock:
            self._counts.clear()
            self._file_counts.clear()

    def is_active(self) -> bool:
        """Check if any indexing is in progress."""
        with self._lock:
            return bool(self._counts) or bool(self._file_counts)

    def to_dict(self) -> dict[str, Any] | None:
        """Return status dict for inclusion in search responses.

        Returns None when idle. When file-level data exists for a collection,
        it takes precedence over job-level counts.
        """
        with self._lock:
            if not self._counts and not self._file_counts:
                return None

            collections: dict[str, Any] = {}
            total_remaining = 0

            # File-level counts (take precedence)
            for coll, counts in self._file_counts.items():
                total = counts.get("total", 0)
                processed = counts.get("processed", 0)
                remaining = max(0, total - processed)
                collections[coll] = {
                    "total": total,
                    "processed": processed,
                    "remaining": remaining,
                }
                total_remaining += remaining

            # Job-level counts (fallback for collections without file-level data)
            for coll, count in self._counts.items():
                if coll not in collections:
                    collections[coll] = count
                    total_remaining += count

            return {
                "active": True,
                "total_remaining": total_remaining,
                "collections": collections,
            }
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_indexing_status.py -v`
Expected: All PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/indexing_status.py tests/test_indexing_status.py
git commit -m "feat: add file-level progress tracking to IndexingStatus"
```

---

### Task 7: Fix stale detection for non-file sources

**Files:**
- Modify: `src/ragling/search.py:221-248`
- Test: `tests/test_search.py`

**Step 1: Write the failing test**

Add to `tests/test_search.py`:

```python
class TestMarkStaleResults:
    """Tests for _mark_stale_results handling non-file sources."""

    def test_non_file_path_not_marked_stale(self) -> None:
        from ragling.search import SearchResult, _mark_stale_results

        results = [
            SearchResult(
                content="test", title="test", metadata={}, score=1.0,
                collection="email", source_path="msg://12345",
                source_type="email",
            ),
        ]
        _mark_stale_results(results, {"msg://12345": None})
        assert results[0].stale is False

    def test_rss_url_not_marked_stale(self) -> None:
        from ragling.search import SearchResult, _mark_stale_results

        results = [
            SearchResult(
                content="test", title="test", metadata={}, score=1.0,
                collection="rss", source_path="https://example.com/article",
                source_type="rss",
            ),
        ]
        _mark_stale_results(results, {"https://example.com/article": None})
        assert results[0].stale is False

    def test_deleted_file_marked_stale(self) -> None:
        from ragling.search import SearchResult, _mark_stale_results

        results = [
            SearchResult(
                content="test", title="test", metadata={}, score=1.0,
                collection="obsidian", source_path="/tmp/nonexistent_file.md",
                source_type="markdown",
            ),
        ]
        _mark_stale_results(results, {"/tmp/nonexistent_file.md": None})
        assert results[0].stale is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_search.py::TestMarkStaleResults -v`
Expected: FAIL — non-file paths get stale=True because os.stat fails on them

**Step 3: Write minimal implementation**

In `src/ragling/search.py`, update `_mark_stale_results` (lines 221-248):

```python
def _mark_stale_results(
    results: list[SearchResult],
    file_modified_at_map: dict[str, str | None],
) -> None:
    """Mark results whose source files have changed or been deleted.

    Only checks paths that start with '/' (filesystem paths). Non-file
    sources (email message IDs, RSS URLs, calibre:// URIs) are skipped.

    Args:
        results: Search results to check (mutated in-place).
        file_modified_at_map: Map from source_path to file_modified_at timestamp.
    """
    stat_cache: dict[str, os.stat_result | None] = {}

    for result in results:
        # Skip non-filesystem paths
        if not result.source_path.startswith("/"):
            continue

        # Use cache to avoid re-statting the same file for multi-chunk results
        if result.source_path not in stat_cache:
            try:
                stat_cache[result.source_path] = os.stat(result.source_path)
            except (FileNotFoundError, OSError):
                stat_cache[result.source_path] = None

        st = stat_cache[result.source_path]
        if st is None:
            result.stale = True
            continue

        indexed_at_str = file_modified_at_map.get(result.source_path)
        if not indexed_at_str:
            continue  # no recorded mtime — can't determine staleness

        try:
            indexed_mtime = datetime.fromisoformat(indexed_at_str).replace(tzinfo=timezone.utc)
            file_mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            if file_mtime > indexed_mtime:
                result.stale = True
        except (ValueError, OSError):
            pass
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_search.py::TestMarkStaleResults -v`
Expected: All PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/search.py tests/test_search.py
git commit -m "fix: skip stale detection for non-file sources (email, RSS, calibre)"
```

---

### Task 8: Surface stale flag in MCP responses

**Files:**
- Modify: `src/ragling/mcp_server.py:433-451`
- Test: `tests/test_mcp_server.py`

**Step 1: Write the failing test**

Add to `tests/test_mcp_server.py`:

```python
class TestStaleFieldInResponse:
    """Tests for stale field appearing in search results."""

    def test_result_dict_includes_stale_field(self) -> None:
        """Verify the result dict construction includes 'stale' key."""
        from ragling.search import SearchResult

        r = SearchResult(
            content="test", title="test", metadata={}, score=1.0,
            collection="obsidian", source_path="/tmp/test.md",
            source_type="markdown", stale=True,
        )
        # Simulate the dict construction from mcp_server.py
        result_dict = {
            "title": r.title,
            "content": r.content,
            "collection": r.collection,
            "source_type": r.source_type,
            "source_path": r.source_path,
            "score": round(r.score, 4),
            "metadata": r.metadata,
            "stale": r.stale,
        }
        assert result_dict["stale"] is True
```

**Step 2: This test passes already (it's pure logic). Write the implementation.**

In `src/ragling/mcp_server.py`, add `"stale": r.stale` to the result_dicts construction (around line 449):

Change:
```python
                "metadata": r.metadata,
```
To:
```python
                "metadata": r.metadata,
                "stale": r.stale,
```

**Step 3: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 4: Commit**

```bash
git add src/ragling/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: surface stale flag in MCP search responses"
```

---

### Task 9: Fix watcher startup condition

**Files:**
- Modify: `src/ragling/cli.py:728`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
class TestWatcherStartupCondition:
    """Tests for watcher starting with obsidian-only configs."""

    def test_obsidian_only_config_triggers_watcher(self, tmp_path: Path) -> None:
        """A config with only obsidian_vaults should still start the watcher."""
        from ragling.watcher import get_watch_paths

        vault = tmp_path / "vault"
        vault.mkdir()

        config = Config(
            obsidian_vaults=[vault],
            embedding_dimensions=4,
        )

        paths = get_watch_paths(config)
        assert len(paths) > 0
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::TestWatcherStartupCondition -v`
Expected: PASS (get_watch_paths already handles this; the bug is in cli.py's condition)

**Step 3: Write the fix**

In `src/ragling/cli.py`, replace line 728:

```python
    if config.home or config.global_paths:
```

With:

```python
    from ragling.watcher import get_watch_paths

    if get_watch_paths(config):
```

**Step 4: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 5: Commit**

```bash
git add src/ragling/cli.py tests/test_cli.py
git commit -m "fix: start watcher for obsidian-only and code-group-only configs"
```

---

### Task 10: Wire `SystemCollectionWatcher` into serve

**Files:**
- Modify: `src/ragling/system_watcher.py`
- Modify: `src/ragling/cli.py`
- Test: `tests/test_system_watcher.py`

**Step 1: Write the failing test**

Add to `tests/test_system_watcher.py`:

```python
class TestStartSystemWatcher:
    """Tests for start_system_watcher convenience function."""

    def test_returns_observer_and_watcher(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from ragling.config import Config
        from ragling.system_watcher import start_system_watcher

        config = Config(
            emclient_db_path=tmp_path / "emclient.db",
            embedding_dimensions=4,
        )
        queue = MagicMock()

        # Create the DB file so the watch directory exists
        (tmp_path / "emclient.db").touch()

        observer, watcher = start_system_watcher(config, queue)
        assert observer.is_alive()
        observer.stop()
        observer.join(timeout=5)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_system_watcher.py::TestStartSystemWatcher -v`
Expected: FAIL — `ImportError: cannot import name 'start_system_watcher'`

**Step 3: Write minimal implementation**

Add to end of `src/ragling/system_watcher.py`:

```python
def start_system_watcher(
    config: Config, queue: IndexingQueue
) -> tuple[Observer, SystemCollectionWatcher]:
    """Start a watchdog observer for system collection databases.

    Args:
        config: Application configuration.
        queue: The indexing queue to submit jobs to.

    Returns:
        Tuple of (observer, watcher) for shutdown cleanup.
    """
    from watchdog.observers import Observer

    watcher = SystemCollectionWatcher(config, queue)
    handler = _SystemDbHandler(watcher)
    observer = Observer()
    observer.daemon = True
    for directory in watcher.get_watch_directories():
        observer.schedule(handler, str(directory), recursive=False)
        logger.info("Watching system DB directory: %s", directory)
    observer.start()
    return observer, watcher
```

Add `Observer` import at the top of the file:

```python
from watchdog.observers import Observer
```

Then wire it into `src/ragling/cli.py` after line 739 (after the watcher block):

```python
    # Start system collection watcher after sync
    def _start_system_watcher_after_sync() -> None:
        sync_done.wait()
        try:
            from ragling.system_watcher import start_system_watcher

            start_system_watcher(config, indexing_queue)
            logger.info("System collection watcher started")
        except Exception:
            logger.exception("Failed to start system collection watcher")

    threading.Thread(
        target=_start_system_watcher_after_sync,
        name="sys-watcher-wait",
        daemon=True,
    ).start()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_system_watcher.py::TestStartSystemWatcher -v`
Expected: PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/system_watcher.py src/ragling/cli.py tests/test_system_watcher.py
git commit -m "feat: wire SystemCollectionWatcher into serve command"
```

---

### Task 11: Wire ConfigWatcher and add shutdown cleanup

**Files:**
- Modify: `src/ragling/indexing_queue.py`
- Modify: `src/ragling/mcp_server.py`
- Modify: `src/ragling/cli.py`
- Test: `tests/test_config_watcher.py`

**Step 1: Write the failing test for `set_config`**

Add to `tests/test_indexing_queue.py`:

```python
class TestSetConfig:
    """Tests for IndexingQueue.set_config()."""

    def test_set_config_replaces_config(self, tmp_path: Path) -> None:
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus

        config1 = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        config2 = config1.with_overrides(embedding_dimensions=8)

        status = IndexingStatus()
        queue = IndexingQueue(config1, status)
        assert queue._config.embedding_dimensions == 4

        queue.set_config(config2)
        assert queue._config.embedding_dimensions == 8
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_indexing_queue.py::TestSetConfig -v`
Expected: FAIL — `AttributeError: 'IndexingQueue' object has no attribute 'set_config'`

**Step 3: Write minimal implementation**

Add to `IndexingQueue` in `src/ragling/indexing_queue.py`, after `shutdown`:

```python
    def set_config(self, config: Config) -> None:
        """Replace the current config.

        Safe under the GIL — attribute assignment is atomic. The worker
        thread reads _config at the start of each job.

        Args:
            config: The new Config instance.
        """
        self._config = config
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_indexing_queue.py::TestSetConfig -v`
Expected: PASS

**Step 5: Write the failing test for config_getter in MCP server**

Add to `tests/test_mcp_server.py`:

```python
class TestConfigGetter:
    """Tests for config_getter parameter in create_server."""

    def test_config_getter_is_accepted(self, tmp_path: Path) -> None:
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
        )

        server = create_server(
            group_name="default",
            config=config,
            config_getter=lambda: config,
        )
        assert server is not None
```

**Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_server.py::TestConfigGetter -v`
Expected: FAIL — `create_server() got an unexpected keyword argument 'config_getter'`

**Step 7: Write implementation**

In `src/ragling/mcp_server.py`, update `create_server` signature:

```python
def create_server(
    group_name: str = "default",
    config: Config | None = None,
    indexing_status: IndexingStatus | None = None,
    indexing_queue: IndexingQueue | None = None,
    config_getter: Callable[[], Config] | None = None,
) -> FastMCP:
```

Add to imports:

```python
from collections.abc import Callable
```

Update `_get_config()` inside `create_server`:

```python
    def _get_config() -> Config:
        """Return an effective Config with the correct group_name."""
        if config_getter:
            return config_getter().with_overrides(group_name=group_name)
        return (server_config or load_config()).with_overrides(group_name=group_name)
```

**Step 8: Wire into cli.py**

In `src/ragling/cli.py`, add ConfigWatcher setup before the `create_server` call:

```python
    # Set up config watching and shutdown
    import atexit

    from ragling.config_watcher import ConfigWatcher

    config_path = ctx.obj.get("config_path")

    def _handle_config_reload(new_config: Config) -> None:
        indexing_queue.set_config(new_config)
        logger.info("Config reloaded, queue updated")

    config_watcher = ConfigWatcher(
        config,
        config_path=config_path or DEFAULT_CONFIG_PATH,
        on_reload=_handle_config_reload,
    )

    def _shutdown() -> None:
        logger.info("Shutting down...")
        indexing_queue.shutdown()
        config_watcher.stop()

    atexit.register(_shutdown)
```

Add `DEFAULT_CONFIG_PATH` import:

```python
    from ragling.config import DEFAULT_CONFIG_PATH
```

Update `create_server` call:

```python
    server = create_server(
        group_name=group,
        config=config,
        indexing_status=indexing_status,
        indexing_queue=indexing_queue,
        config_getter=config_watcher.get_config,
    )
```

**Step 9: Run tests**

Run: `uv run pytest tests/test_indexing_queue.py::TestSetConfig tests/test_mcp_server.py::TestConfigGetter -v`
Expected: All PASS

**Step 10: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 11: Commit**

```bash
git add src/ragling/indexing_queue.py src/ragling/mcp_server.py src/ragling/cli.py tests/test_indexing_queue.py tests/test_mcp_server.py
git commit -m "feat: wire ConfigWatcher into serve with shutdown cleanup"
```

---

### Task 12: Add metadata cache to search

**Files:**
- Modify: `src/ragling/search.py:157-178`
- Modify: `src/ragling/db.py:54-123`
- Test: `tests/test_search.py`, `tests/test_db.py`

**Step 1: Write the failing test for collection index**

Add to `tests/test_db.py`:

```python
class TestCollectionIndex:
    """Tests for idx_documents_collection_id index."""

    def test_index_exists_after_init(self, tmp_path: Path) -> None:
        from ragling.db import get_connection, init_db

        config = Config(db_path=tmp_path / "test.db", embedding_dimensions=4)
        conn = get_connection(config)
        init_db(conn, config)

        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {row[0] for row in indexes}
        assert "idx_documents_collection_id" in index_names
        conn.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::TestCollectionIndex -v`
Expected: FAIL — `idx_documents_collection_id` not found

**Step 3: Write the index**

In `src/ragling/db.py`, add to the `init_db` executescript (before the `meta` table, around line 121):

```sql
        CREATE INDEX IF NOT EXISTS idx_documents_collection_id
            ON documents(collection_id);
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py::TestCollectionIndex -v`
Expected: PASS

**Step 5: Add metadata cache to _batch_load_metadata**

Update `_batch_load_metadata` in `src/ragling/search.py`:

```python
def _batch_load_metadata(
    conn: sqlite3.Connection,
    doc_ids: list[int],
    cache: dict[int, sqlite3.Row] | None = None,
) -> dict[int, sqlite3.Row]:
    """Load metadata for multiple documents in a single query.

    Uses an optional cache to skip already-loaded IDs.

    Returns a dict mapping document ID to its joined row data.
    """
    if not doc_ids:
        return {}

    if cache is not None:
        uncached = [id for id in doc_ids if id not in cache]
        if not uncached:
            return {id: cache[id] for id in doc_ids if id in cache}
        doc_ids = uncached

    placeholders = ",".join("?" * len(doc_ids))
    rows = conn.execute(
        f"""
        SELECT d.id, d.content, d.title, d.metadata,
               d.collection_id, c.name AS collection_name,
               c.collection_type, s.source_type, s.source_path,
               s.file_modified_at
        FROM documents d
        JOIN collections c ON d.collection_id = c.id
        JOIN sources s ON d.source_id = s.id
        WHERE d.id IN ({placeholders})
        """,
        doc_ids,
    ).fetchall()

    result = {row["id"]: row for row in rows}

    if cache is not None:
        cache.update(result)
        return {id: cache[id] for id in (uncached + [id for id in doc_ids if id in cache]) if id in cache}

    return result
```

Then update `_apply_filters` and `search` to pass the cache through:

In `_apply_filters`, add `cache` parameter and pass to `_batch_load_metadata`.

In `search()`, create `metadata_cache` at the top and pass it through all calls.

**Step 6: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 7: Commit**

```bash
git add src/ragling/search.py src/ragling/db.py tests/test_search.py tests/test_db.py
git commit -m "feat: add metadata cache and collection_id index for search efficiency"
```

---

### Task 13: Improve `rag_search` docstring

**Files:**
- Modify: `src/ragling/mcp_server.py:301-401`

**Step 1: Rewrite the docstring**

Replace the `rag_search` docstring (lines 301-401) with:

```python
        """Search personal knowledge across indexed collections.

        Combines vector similarity (semantic meaning) with full-text keyword
        matching using Reciprocal Rank Fusion for best results.

        Collections are organized by type:
        - **system**: obsidian, email, calibre, rss (auto-configured)
        - **code**: git repo groups indexed by topic or org
        - **project**: user-created document folders

        The ``collection`` parameter filters by name (exact) or type
        (``"system"``, ``"project"``, ``"code"``).

        Each result includes a ``source_uri`` for opening the original:
        obsidian:// for vault files, vscode:// for code, file:// for
        documents, https:// for RSS. Email and commits return null.

        Args:
            query: Search text — natural language or keywords.
            collection: Filter by collection name or type. Omit to search all.
            top_k: Number of results to return (default 10).
            source_type: Filter by type: 'markdown', 'pdf', 'email', 'code', etc.
            date_from: Only results after this date (YYYY-MM-DD).
            date_to: Only results before this date (YYYY-MM-DD).
            sender: Filter by email sender (case-insensitive substring).
            author: Filter by book author (case-insensitive substring).

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
        """
```

**Step 2: Run check**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 3: Commit**

```bash
git add src/ragling/mcp_server.py
git commit -m "docs: improve rag_search docstring with Pythonic conventions"
```

---

### Task 14: Add `host.docker.internal` to TLS SAN

**Files:**
- Modify: `src/ragling/tls.py:133-139`
- Test: `tests/test_tls.py`

**Step 1: Write the failing test**

Add to `tests/test_tls.py`:

```python
class TestDockerSAN:
    """Tests for host.docker.internal in server certificate SAN."""

    def test_server_san_includes_docker_internal(self, tmp_path: Path) -> None:
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        server = x509.load_pem_x509_certificate(cfg.server_cert.read_bytes())

        san = server.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "host.docker.internal" in dns_names
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tls.py::TestDockerSAN -v`
Expected: FAIL — `host.docker.internal` not in SAN

**Step 3: Write implementation**

In `src/ragling/tls.py`, update the SAN in `_generate_server_cert` (lines 134-139):

```python
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName("host.docker.internal"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tls.py::TestDockerSAN -v`
Expected: PASS

**Step 5: Run full check**

Run: `uv run pytest tests/test_tls.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/tls.py tests/test_tls.py
git commit -m "feat: add host.docker.internal to server cert SAN for Docker"
```

---

### Task 15: Add near-expiry warning and fix HTTPS issuer

**Files:**
- Modify: `src/ragling/tls.py:68-70`
- Modify: `src/ragling/mcp_server.py:282`
- Test: `tests/test_tls.py`, `tests/test_mcp_server.py`

**Step 1: Write the failing test for near-expiry**

Add to `tests/test_tls.py`:

```python
class TestNearExpiryWarning:
    """Tests for certificate near-expiry warning."""

    def test_near_expiry_logs_warning(self, tmp_path: Path, caplog) -> None:
        import logging

        from ragling.tls import ensure_tls_certs

        tls_dir = tmp_path / "tls"
        cfg = ensure_tls_certs(tls_dir)

        # Replace server cert with one expiring in 15 days
        _write_near_expiry_cert(cfg, days_remaining=15)

        with caplog.at_level(logging.WARNING, logger="ragling.tls"):
            ensure_tls_certs(tls_dir)

        assert any("expires in" in r.message for r in caplog.records)


def _write_near_expiry_cert(cfg: TLSConfig, days_remaining: int = 15) -> None:
    """Helper: overwrite server cert with one expiring in N days."""
    from datetime import timedelta

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    ca_cert = x509.load_pem_x509_certificate(cfg.ca_cert.read_bytes())
    ca_key = serialization.load_pem_private_key(cfg.ca_key.read_bytes(), password=None)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=350))
        .not_valid_after(now + timedelta(days=days_remaining))
        .sign(ca_key, hashes.SHA256())
    )

    cfg.server_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cfg.server_key.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tls.py::TestNearExpiryWarning -v`
Expected: FAIL — no warning logged

**Step 3: Write implementation**

In `src/ragling/tls.py`, update `ensure_tls_certs` after line 70 (`_generate_server_cert(cfg)`):

```python
    elif _is_expired(cfg.server_cert):
        logger.info("Server certificate expired, regenerating")
        _generate_server_cert(cfg)
    else:
        # Check for near-expiry
        cert = x509.load_pem_x509_certificate(cfg.server_cert.read_bytes())
        now = datetime.now(timezone.utc)
        days_left = (cert.not_valid_after_utc - now).days
        if days_left < 30:
            logger.warning("Server certificate expires in %d days", days_left)
```

In `src/ragling/mcp_server.py`, change line 282:

```python
                "http://localhost"
```
To:
```python
                "https://localhost"
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tls.py::TestNearExpiryWarning -v`
Expected: PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/tls.py src/ragling/mcp_server.py tests/test_tls.py
git commit -m "feat: add cert near-expiry warning and fix HTTPS issuer URL"
```

---

### Task 16: Remove dead `create_ssl_context()`

**Files:**
- Modify: `src/ragling/tls.py:150-161`
- Modify: `tests/test_tls.py:212-221`

**Step 1: Delete the function and its test**

In `src/ragling/tls.py`, delete `create_ssl_context` (lines 150-161).

Remove the `ssl` import from line 12 (it's only used by `create_ssl_context`).

In `tests/test_tls.py`, delete `TestCreateSSLContext` class (lines 212-221).

**Step 2: Run full check**

Run: `uv run pytest tests/test_tls.py && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 3: Commit**

```bash
git add src/ragling/tls.py tests/test_tls.py
git commit -m "refactor: remove unused create_ssl_context()"
```

---

### Task 17: Enable ruff S608

**Files:**
- Modify: `local-rag/pyproject.toml`
- Possibly modify: multiple source files with `# noqa: S608` annotations

**Step 1: Add S608 to ruff config**

In `pyproject.toml`, add a lint section (currently only `[tool.ruff]` exists with `target-version` and `line-length`):

```toml
[tool.ruff.lint]
extend-select = ["S608"]
```

**Step 2: Run ruff to see what gets flagged**

Run: `uv run ruff check .`

**Step 3: Add `# noqa: S608` with explanations to each flagged line**

Common flagged patterns will be f-string SQL like:

- `db.py`: `f"CREATE VIRTUAL TABLE ... vec0(embedding float[{dim}] ...)"` — dim from config
- `search.py`: `f"WHERE d.id IN ({placeholders})"` — parameterized IDs, not user input
- `db.py`: `f"SELECT id FROM collections WHERE name IN ({','.join('?' * ...)})"` — parameterized

Add `# noqa: S608` with explanation to each:

```python
# noqa: S608 — dim is from config, not user input
# noqa: S608 — placeholders are parameterized ?-marks, not user input
```

**Step 4: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 5: Commit**

```bash
git add pyproject.toml src/
git commit -m "feat: enable ruff S608 SQL injection detection with audit trail"
```

---

### Task 18: Final verification

**Step 1: Run complete quality gate**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 2: Manual verification checklist**

1. Start `ragling serve --sse`, verify TLS handshake succeeds with `host.docker.internal` SAN
2. Edit `~/.ragling/config.json` while server runs, verify "Config reloaded" in logs
3. Call `rag_index("obsidian")` via MCP while startup sync is running — no `database is locked`
4. Search for an email — NOT marked `[STALE]`
5. Modify an indexed file, search for it — IS marked `[STALE]`
6. Verify `indexing_status` in search responses shows file-level remaining counts
