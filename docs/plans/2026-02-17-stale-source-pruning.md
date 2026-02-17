# Stale Source Pruning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Automatically remove vectors, documents, and source rows for files that have been deleted from disk, both during batch index runs and in real-time via the filesystem watcher.

**Architecture:** Two new functions in `base.py` (`delete_source` and `prune_stale_sources`) provide the shared pruning logic. Batch indexers (project, obsidian, calibre) call `prune_stale_sources` after their main loop. The filesystem watcher adds `on_deleted` support, and the sync callback checks `path.exists()` at flush time to decide whether to re-index or prune. The git indexer's private `_delete_source` is replaced with the shared function.

**Tech Stack:** Python, SQLite, watchdog, pytest

**Pruning filter:** Only sources where `file_hash IS NOT NULL AND source_path LIKE '/%'` are eligible. This correctly excludes email (no file_hash), RSS (no file_hash), git commits (virtual URIs), and calibre description-only entries (calibre:// URIs).

---

### Task 1: Add `delete_source` to `base.py`

**Files:**
- Modify: `src/ragling/indexers/base.py`
- Test: `tests/test_base_indexer.py` (create)

**Step 1: Write the failing test**

Create `tests/test_base_indexer.py`:

```python
"""Tests for ragling.indexers.base module -- delete and prune functions."""

import sqlite3
from pathlib import Path

from ragling.config import Config
from ragling.db import get_connection, init_db
from ragling.indexers.base import delete_source, upsert_source_with_chunks


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create an initialized in-memory-like test DB."""
    config = Config(
        db_path=tmp_path / "test.db",
        embedding_dimensions=4,
    )
    conn = get_connection(config)
    init_db(conn, config)
    return conn


def _insert_source(conn: sqlite3.Connection, collection_id: int, source_path: str) -> int:
    """Insert a source with one document and one vector for testing."""
    from ragling.chunker import Chunk
    from ragling.embeddings import serialize_float32

    return upsert_source_with_chunks(
        conn,
        collection_id=collection_id,
        source_path=source_path,
        source_type="plaintext",
        chunks=[Chunk(text="test content", title="test", chunk_index=0)],
        embeddings=[[0.1, 0.2, 0.3, 0.4]],
        file_hash="abc123",
    )


class TestDeleteSource:
    def test_deletes_source_and_documents(self, tmp_path: Path) -> None:
        conn = _make_conn(tmp_path)
        from ragling.db import get_or_create_collection

        cid = get_or_create_collection(conn, "test-coll", "project")
        _insert_source(conn, cid, "/tmp/file.txt")

        # Verify source exists
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1

        delete_source(conn, cid, "/tmp/file.txt")

        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM vec_documents").fetchone()[0] == 0

    def test_noop_when_source_does_not_exist(self, tmp_path: Path) -> None:
        conn = _make_conn(tmp_path)
        from ragling.db import get_or_create_collection

        cid = get_or_create_collection(conn, "test-coll", "project")

        # Should not raise
        delete_source(conn, cid, "/tmp/nonexistent.txt")

    def test_only_deletes_matching_source(self, tmp_path: Path) -> None:
        conn = _make_conn(tmp_path)
        from ragling.db import get_or_create_collection

        cid = get_or_create_collection(conn, "test-coll", "project")
        _insert_source(conn, cid, "/tmp/keep.txt")
        _insert_source(conn, cid, "/tmp/delete.txt")

        delete_source(conn, cid, "/tmp/delete.txt")

        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        remaining = conn.execute("SELECT source_path FROM sources").fetchone()
        assert remaining["source_path"] == "/tmp/keep.txt"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_base_indexer.py -v`
Expected: FAIL with `ImportError: cannot import name 'delete_source'`

**Step 3: Write minimal implementation**

Add to `src/ragling/indexers/base.py`, after `upsert_source_with_chunks`:

```python
def delete_source(
    conn: sqlite3.Connection,
    collection_id: int,
    source_path: str,
) -> bool:
    """Delete a source and its documents/vectors from the database.

    Removes the source row, all associated document rows, their FTS entries
    (via trigger), and vector embeddings. No-op if the source doesn't exist.

    Args:
        conn: SQLite database connection.
        collection_id: Collection the source belongs to.
        source_path: The source_path to delete.

    Returns:
        True if a source was deleted, False if it didn't exist.
    """
    existing = conn.execute(
        "SELECT id FROM sources WHERE collection_id = ? AND source_path = ?",
        (collection_id, source_path),
    ).fetchone()

    if not existing:
        return False

    source_id = existing["id"]

    # Delete vectors for all documents of this source
    old_doc_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM documents WHERE source_id = ?", (source_id,)
        ).fetchall()
    ]
    if old_doc_ids:
        placeholders = ",".join("?" * len(old_doc_ids))
        conn.execute(
            f"DELETE FROM vec_documents WHERE document_id IN ({placeholders})",
            old_doc_ids,
        )

    # Delete documents (triggers handle FTS cleanup)
    conn.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))

    # Delete the source row
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    conn.commit()
    logger.info("Deleted source: %s", source_path)
    return True
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_base_indexer.py -v`
Expected: All 3 tests PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add tests/test_base_indexer.py src/ragling/indexers/base.py
git commit -m "feat: add delete_source function to base indexer"
```

---

### Task 2: Add `prune_stale_sources` to `base.py`

**Files:**
- Modify: `src/ragling/indexers/base.py`
- Modify: `tests/test_base_indexer.py`

**Step 1: Write the failing tests**

Add to `tests/test_base_indexer.py`:

```python
from ragling.indexers.base import prune_stale_sources


class TestPruneStaleSources:
    def test_prunes_source_whose_file_is_gone(self, tmp_path: Path) -> None:
        conn = _make_conn(tmp_path)
        from ragling.db import get_or_create_collection

        cid = get_or_create_collection(conn, "test-coll", "project")

        # Create a real file, index it, then delete it
        real_file = tmp_path / "doc.txt"
        real_file.write_text("content")
        _insert_source(conn, cid, str(real_file))
        real_file.unlink()

        pruned = prune_stale_sources(conn, cid)

        assert pruned == 1
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0

    def test_keeps_source_whose_file_exists(self, tmp_path: Path) -> None:
        conn = _make_conn(tmp_path)
        from ragling.db import get_or_create_collection

        cid = get_or_create_collection(conn, "test-coll", "project")

        real_file = tmp_path / "doc.txt"
        real_file.write_text("content")
        _insert_source(conn, cid, str(real_file))

        pruned = prune_stale_sources(conn, cid)

        assert pruned == 0
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1

    def test_skips_sources_without_file_hash(self, tmp_path: Path) -> None:
        """Sources like email/RSS have no file_hash and should not be pruned."""
        conn = _make_conn(tmp_path)
        from ragling.db import get_or_create_collection

        cid = get_or_create_collection(conn, "test-coll", "project")

        # Insert a source with no file_hash (like email)
        conn.execute(
            "INSERT INTO sources (collection_id, source_type, source_path) "
            "VALUES (?, 'email', 'msg://12345')",
            (cid,),
        )
        conn.commit()

        pruned = prune_stale_sources(conn, cid)

        assert pruned == 0
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1

    def test_skips_sources_with_virtual_uri(self, tmp_path: Path) -> None:
        """Sources like calibre descriptions use virtual URIs and should not be pruned."""
        conn = _make_conn(tmp_path)
        from ragling.db import get_or_create_collection

        cid = get_or_create_collection(conn, "test-coll", "project")

        # Insert a source with file_hash but non-filesystem path
        conn.execute(
            "INSERT INTO sources (collection_id, source_type, source_path, file_hash) "
            "VALUES (?, 'calibre-description', 'calibre:///lib/book', 'hash123')",
            (cid,),
        )
        conn.commit()

        pruned = prune_stale_sources(conn, cid)

        assert pruned == 0
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1

    def test_mixed_sources_only_prunes_missing_files(self, tmp_path: Path) -> None:
        conn = _make_conn(tmp_path)
        from ragling.db import get_or_create_collection

        cid = get_or_create_collection(conn, "test-coll", "project")

        # Existing file -- should keep
        existing = tmp_path / "keep.txt"
        existing.write_text("keep")
        _insert_source(conn, cid, str(existing))

        # Deleted file -- should prune
        deleted = tmp_path / "gone.txt"
        deleted.write_text("gone")
        _insert_source(conn, cid, str(deleted))
        deleted.unlink()

        # Virtual URI -- should skip
        conn.execute(
            "INSERT INTO sources (collection_id, source_type, source_path, file_hash) "
            "VALUES (?, 'calibre-description', 'calibre:///lib/book', 'hash123')",
            (cid,),
        )
        conn.commit()

        pruned = prune_stale_sources(conn, cid)

        assert pruned == 1
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 2
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_base_indexer.py::TestPruneStaleSources -v`
Expected: FAIL with `ImportError: cannot import name 'prune_stale_sources'`

**Step 3: Write minimal implementation**

Add to `src/ragling/indexers/base.py`, after `delete_source`:

```python
def prune_stale_sources(conn: sqlite3.Connection, collection_id: int) -> int:
    """Remove sources whose backing files no longer exist on disk.

    Only checks sources that have a file_hash (file-backed) and an absolute
    filesystem path (starts with /). Skips virtual URIs and sources without
    file hashes (email, RSS, git commits).

    Args:
        conn: SQLite database connection.
        collection_id: Collection to prune.

    Returns:
        Number of sources pruned.
    """
    rows = conn.execute(
        "SELECT source_path FROM sources "
        "WHERE collection_id = ? AND file_hash IS NOT NULL AND source_path LIKE '/%'",
        (collection_id,),
    ).fetchall()

    pruned = 0
    for row in rows:
        source_path = row["source_path"]
        if not Path(source_path).exists():
            delete_source(conn, collection_id, source_path)
            pruned += 1

    if pruned:
        logger.info("Pruned %d stale source(s) from collection %d", pruned, collection_id)

    return pruned
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_base_indexer.py -v`
Expected: All tests PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add tests/test_base_indexer.py src/ragling/indexers/base.py
git commit -m "feat: add prune_stale_sources function to base indexer"
```

---

### Task 3: Add `pruned` field to `IndexResult`

**Files:**
- Modify: `src/ragling/indexers/base.py`
- Modify: `tests/test_base_indexer.py`

**Step 1: Write the failing test**

Add to `tests/test_base_indexer.py`:

```python
from ragling.indexers.base import IndexResult


class TestIndexResultPruned:
    def test_pruned_defaults_to_zero(self) -> None:
        result = IndexResult()
        assert result.pruned == 0

    def test_str_includes_pruned_when_nonzero(self) -> None:
        result = IndexResult(indexed=5, skipped=10, pruned=3, errors=0, total_found=15)
        s = str(result)
        assert "Pruned: 3" in s

    def test_str_omits_pruned_when_zero(self) -> None:
        result = IndexResult(indexed=5, skipped=10, pruned=0, errors=0, total_found=15)
        s = str(result)
        assert "Pruned" not in s
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_base_indexer.py::TestIndexResultPruned -v`
Expected: FAIL with `TypeError: unexpected keyword argument 'pruned'`

**Step 3: Write minimal implementation**

Modify `IndexResult` in `src/ragling/indexers/base.py`:

Add `pruned: int = 0` field after `skipped_empty`. Update `__str__` to include pruned conditionally:

```python
@dataclass
class IndexResult:
    """Summary of an indexing run."""

    indexed: int = 0
    skipped: int = 0
    skipped_empty: int = 0
    pruned: int = 0
    errors: int = 0
    total_found: int = 0
    error_messages: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        parts = [
            f"Indexed: {self.indexed}",
            f"Skipped: {self.skipped}",
        ]
        if self.skipped_empty:
            parts.append(f"Skipped empty: {self.skipped_empty}")
        if self.pruned:
            parts.append(f"Pruned: {self.pruned}")
        parts.extend(
            [
                f"Errors: {self.errors}",
                f"Total found: {self.total_found}",
            ]
        )
        return ", ".join(parts)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_base_indexer.py -v`
Expected: All tests PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add tests/test_base_indexer.py src/ragling/indexers/base.py
git commit -m "feat: add pruned field to IndexResult"
```

---

### Task 4: Integrate pruning into `ProjectIndexer`

**Files:**
- Modify: `src/ragling/indexers/project.py`
- Modify: `tests/test_project_indexer.py`

**Step 1: Write the failing test**

Add to `tests/test_project_indexer.py`:

```python
from unittest.mock import MagicMock, patch


class TestProjectIndexerPruning:
    def test_prune_called_after_indexing(self, tmp_path: Path) -> None:
        """ProjectIndexer.index() calls prune_stale_sources after processing files."""
        from ragling.config import Config
        from ragling.db import get_connection, init_db
        from ragling.indexers.project import ProjectIndexer

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )
        conn = get_connection(config)
        init_db(conn, config)

        indexer = ProjectIndexer("test-coll", [tmp_path])

        with patch("ragling.indexers.project.prune_stale_sources", return_value=2) as mock_prune:
            result = indexer.index(conn, config)

        mock_prune.assert_called_once()
        assert result.pruned == 2
        conn.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_project_indexer.py::TestProjectIndexerPruning -v`
Expected: FAIL (prune_stale_sources not imported or called)

**Step 3: Write minimal implementation**

Modify `src/ragling/indexers/project.py`:

Add import:
```python
from ragling.indexers.base import BaseIndexer, IndexResult, file_hash, upsert_source_with_chunks, prune_stale_sources
```

Add pruning call at the end of `ProjectIndexer.index()`, just before the return:

```python
        # Prune sources whose files no longer exist
        pruned = prune_stale_sources(conn, collection_id)

        logger.info(
            "Project indexer done: %d indexed, %d skipped, %d errors out of %d files",
            indexed,
            skipped,
            errors,
            total_found,
        )

        return IndexResult(
            indexed=indexed, skipped=skipped, pruned=pruned, errors=errors, total_found=total_found
        )
```

Note: move the `prune_stale_sources` call before the log line so the log can include it if desired, or keep the log as-is since pruning is logged separately.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_project_indexer.py -v`
Expected: All tests PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/indexers/project.py tests/test_project_indexer.py
git commit -m "feat: prune stale sources after project indexing"
```

---

### Task 5: Integrate pruning into `ObsidianIndexer`

**Files:**
- Modify: `src/ragling/indexers/obsidian.py`
- Modify: `tests/test_project_indexer.py` (obsidian tests live here)

**Step 1: Write the failing test**

Add to `tests/test_project_indexer.py`:

```python
class TestObsidianIndexerPruning:
    def test_prune_called_after_indexing(self, tmp_path: Path) -> None:
        """ObsidianIndexer.index() calls prune_stale_sources after processing files."""
        from ragling.config import Config
        from ragling.db import get_connection, init_db
        from ragling.indexers.obsidian import ObsidianIndexer

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )
        conn = get_connection(config)
        init_db(conn, config)

        indexer = ObsidianIndexer([vault])

        with patch("ragling.indexers.obsidian.prune_stale_sources", return_value=1) as mock_prune:
            result = indexer.index(conn, config)

        mock_prune.assert_called_once()
        assert result.pruned == 1
        conn.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_project_indexer.py::TestObsidianIndexerPruning -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Modify `src/ragling/indexers/obsidian.py`:

Add import:
```python
from ragling.indexers.base import BaseIndexer, IndexResult, file_hash, upsert_source_with_chunks, prune_stale_sources
```

Add pruning call at the end of `ObsidianIndexer.index()`, just before the log and return:

```python
        # Prune sources whose files no longer exist
        pruned = prune_stale_sources(conn, collection_id)

        logger.info(
            "Obsidian indexing complete: %d found, %d indexed, %d skipped, %d errors",
            total_found,
            indexed,
            skipped,
            errors,
        )
        return IndexResult(
            indexed=indexed, skipped=skipped, pruned=pruned, errors=errors, total_found=total_found
        )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_project_indexer.py -v`
Expected: All tests PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/indexers/obsidian.py tests/test_project_indexer.py
git commit -m "feat: prune stale sources after obsidian indexing"
```

---

### Task 6: Integrate pruning into `CalibreIndexer`

**Files:**
- Modify: `src/ragling/indexers/calibre_indexer.py`
- Modify: `tests/test_project_indexer.py`

**Step 1: Write the failing test**

Add to `tests/test_project_indexer.py`:

```python
class TestCalibreIndexerPruning:
    def test_prune_called_after_indexing(self, tmp_path: Path) -> None:
        """CalibreIndexer.index() calls prune_stale_sources after processing books."""
        from ragling.config import Config
        from ragling.db import get_connection, init_db
        from ragling.indexers.calibre_indexer import CalibreIndexer

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )
        conn = get_connection(config)
        init_db(conn, config)

        # Empty library path - no books to index, but prune should still run
        lib = tmp_path / "CalibreLibrary"
        lib.mkdir()
        indexer = CalibreIndexer([lib])

        with (
            patch("ragling.indexers.calibre_indexer.parse_calibre_library", return_value=[]),
            patch(
                "ragling.indexers.calibre_indexer.prune_stale_sources", return_value=3
            ) as mock_prune,
        ):
            result = indexer.index(conn, config)

        mock_prune.assert_called_once()
        assert result.pruned == 3
        conn.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_project_indexer.py::TestCalibreIndexerPruning -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Modify `src/ragling/indexers/calibre_indexer.py`:

Add `prune_stale_sources` to the import from base:
```python
from ragling.indexers.base import BaseIndexer, IndexResult, file_hash, upsert_source_with_chunks, prune_stale_sources
```

Add pruning call at the end of `CalibreIndexer.index()`, just before the log and return:

```python
        # Prune sources whose files no longer exist
        pruned = prune_stale_sources(conn, collection_id)

        logger.info(
            "Calibre indexing complete: %d found, %d indexed, %d skipped, %d errors",
            total_found,
            indexed,
            skipped,
            errors,
        )
        return IndexResult(
            indexed=indexed, skipped=skipped, pruned=pruned, errors=errors, total_found=total_found
        )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_project_indexer.py -v`
Expected: All tests PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/indexers/calibre_indexer.py tests/test_project_indexer.py
git commit -m "feat: prune stale sources after calibre indexing"
```

---

### Task 7: Replace git indexer's `_delete_source` with shared `delete_source`

**Files:**
- Modify: `src/ragling/indexers/git_indexer.py`

**Step 1: Check existing tests pass**

Run: `uv run pytest -v`
Expected: All PASS (baseline before refactoring)

**Step 2: Refactor git indexer**

In `src/ragling/indexers/git_indexer.py`:

1. Add `delete_source` to the import from base:
```python
from ragling.indexers.base import BaseIndexer, IndexResult, file_hash, upsert_source_with_chunks, delete_source
```

2. Replace the call at line 530:
```python
# Before:
self._delete_source(conn, collection_id, source_path)

# After:
delete_source(conn, collection_id, source_path)
```

3. Delete the `_delete_source` method entirely (lines 598-626).

**Step 3: Run tests to verify nothing broke**

Run: `uv run pytest -v`
Expected: All PASS

**Step 4: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 5: Commit**

```bash
git add src/ragling/indexers/git_indexer.py
git commit -m "refactor: replace git indexer _delete_source with shared delete_source"
```

---

### Task 8: Add `on_deleted` to watcher

**Files:**
- Modify: `src/ragling/watcher.py`
- Create: `tests/test_watcher.py`

**Step 1: Write the failing test**

Create `tests/test_watcher.py`:

```python
"""Tests for ragling.watcher module -- deletion handling."""

from pathlib import Path
from unittest.mock import MagicMock

from watchdog.events import FileDeletedEvent

from ragling.watcher import DebouncedIndexQueue, _Handler


class TestHandlerOnDeleted:
    def test_deleted_file_is_enqueued(self) -> None:
        queue = MagicMock(spec=DebouncedIndexQueue)
        handler = _Handler(queue, {".md", ".txt"})

        event = FileDeletedEvent(src_path="/tmp/notes.md")
        handler.on_deleted(event)

        queue.enqueue.assert_called_once_with(Path("/tmp/notes.md"))

    def test_deleted_unsupported_extension_ignored(self) -> None:
        queue = MagicMock(spec=DebouncedIndexQueue)
        handler = _Handler(queue, {".md", ".txt"})

        event = FileDeletedEvent(src_path="/tmp/photo.raw")
        handler.on_deleted(event)

        queue.enqueue.assert_not_called()

    def test_deleted_directory_ignored(self) -> None:
        queue = MagicMock(spec=DebouncedIndexQueue)
        handler = _Handler(queue, {".md", ".txt"})

        event = FileDeletedEvent(src_path="/tmp/somedir")
        event._is_directory = True  # watchdog sets this for dir events
        handler.on_deleted(event)

        queue.enqueue.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_watcher.py -v`
Expected: FAIL with `AttributeError: '_Handler' object has no attribute 'on_deleted'`

**Step 3: Write minimal implementation**

Add to `_Handler` class in `src/ragling/watcher.py`:

```python
    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file deletion events."""
        self._handle(event)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_watcher.py -v`
Expected: All tests PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/watcher.py tests/test_watcher.py
git commit -m "feat: add on_deleted handler to filesystem watcher"
```

---

### Task 9: Update sync `_index_file` to prune deleted files

**Files:**
- Modify: `src/ragling/sync.py`
- Modify: `tests/test_sync.py`

**Step 1: Write the failing test**

Add to `tests/test_sync.py`:

```python
class TestIndexFileDeleted:
    """Tests for _index_file handling deleted files."""

    def test_deleted_file_calls_delete_source(self, tmp_path: Path) -> None:
        from ragling.sync import _index_file

        home = tmp_path / "groups"
        user_dir = home / "kitchen"
        user_dir.mkdir(parents=True)

        # File path that doesn't exist on disk (simulating deletion)
        deleted_file = user_dir / "gone.md"

        config = Config(
            home=home,
            users={"kitchen": UserConfig(api_key="k")},
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        with (
            patch("ragling.sync.get_connection") as mock_get_conn,
            patch("ragling.sync.init_db"),
            patch("ragling.sync.delete_source") as mock_delete,
            patch("ragling.sync.get_or_create_collection", return_value=1),
        ):
            mock_conn = MagicMock()
            mock_get_conn.return_value = mock_conn

            _index_file(deleted_file, config)

            mock_delete.assert_called_once_with(mock_conn, 1, str(deleted_file.resolve()))
            mock_conn.close.assert_called_once()

    def test_existing_file_still_indexes(self, tmp_path: Path) -> None:
        """Existing files should be indexed as before, not pruned."""
        from ragling.sync import _index_file

        home = tmp_path / "groups"
        user_dir = home / "kitchen"
        user_dir.mkdir(parents=True)
        test_file = user_dir / "notes.md"
        test_file.write_text("# Notes")

        config = Config(
            home=home,
            users={"kitchen": UserConfig(api_key="k")},
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        with (
            patch("ragling.db.get_connection") as mock_get_conn,
            patch("ragling.db.init_db"),
            patch("ragling.doc_store.DocStore") as MockDocStore,
            patch("ragling.indexers.project.ProjectIndexer") as MockProject,
        ):
            mock_conn = MagicMock()
            mock_get_conn.return_value = mock_conn
            mock_doc_store = MagicMock()
            MockDocStore.return_value = mock_doc_store
            mock_indexer = MagicMock()
            mock_indexer.index.return_value = MagicMock(
                indexed=1, skipped=0, errors=0, total_found=1
            )
            MockProject.return_value = mock_indexer

            _index_file(test_file, config)

            MockProject.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sync.py::TestIndexFileDeleted -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Modify `_index_file` in `src/ragling/sync.py`:

```python
def _index_file(file_path: Path, config: Config) -> None:
    """Index or re-index a single file, or prune it if deleted.

    If the file exists on disk, re-indexes it using the project indexer.
    If the file has been deleted, removes its source and vectors from the DB.

    Args:
        file_path: Path to the changed or deleted file.
        config: Application configuration.
    """
    from ragling.db import get_connection, get_or_create_collection, init_db
    from ragling.indexers.base import delete_source

    collection = map_file_to_collection(file_path, config)
    if collection is None:
        logger.warning("Cannot map file to collection: %s", file_path)
        return

    if not file_path.exists():
        # File was deleted -- prune from DB
        conn = get_connection(config)
        init_db(conn, config)
        try:
            collection_id = get_or_create_collection(conn, collection, "project")
            delete_source(conn, collection_id, str(file_path.resolve()))
        except Exception:
            logger.exception("Error pruning deleted file: %s", file_path)
        finally:
            conn.close()
        return

    # File exists -- re-index
    from ragling.doc_store import DocStore
    from ragling.indexers.project import ProjectIndexer

    conn = get_connection(config)
    init_db(conn, config)
    doc_store = DocStore(config.shared_db_path)

    try:
        indexer = ProjectIndexer(collection, [file_path.parent], doc_store=doc_store)
        indexer.index(conn, config)
    except Exception:
        logger.exception("Error indexing file: %s", file_path)
    finally:
        doc_store.close()
        conn.close()
```

Note: The imports for `get_connection`, `init_db`, `get_or_create_collection`, and `delete_source` are moved to be accessible in both branches. The existing `from ragling.db import get_connection, init_db` import inside the function needs to be updated to also import `get_or_create_collection`. The `delete_source` import comes from `ragling.indexers.base`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sync.py -v`
Expected: All tests PASS

**Step 5: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 6: Commit**

```bash
git add src/ragling/sync.py tests/test_sync.py
git commit -m "feat: prune deleted files in watcher callback"
```

---

### Task 10: Final integration test

**Files:**
- Modify: `tests/test_base_indexer.py`

**Step 1: Write an end-to-end test**

Add to `tests/test_base_indexer.py`:

```python
class TestPruneEndToEnd:
    """End-to-end: index files, delete some, prune, verify search wouldn't find them."""

    def test_full_lifecycle(self, tmp_path: Path) -> None:
        conn = _make_conn(tmp_path)
        from ragling.db import get_or_create_collection

        cid = get_or_create_collection(conn, "e2e", "project")

        # Create and index 3 files
        files = []
        for i in range(3):
            f = tmp_path / f"doc{i}.txt"
            f.write_text(f"Content {i}")
            _insert_source(conn, cid, str(f))
            files.append(f)

        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 3

        # Delete 2 of the 3 files
        files[0].unlink()
        files[2].unlink()

        # Prune
        pruned = prune_stale_sources(conn, cid)

        assert pruned == 2
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM vec_documents").fetchone()[0] == 1

        # The remaining source is the one whose file still exists
        remaining = conn.execute("SELECT source_path FROM sources").fetchone()
        assert remaining["source_path"] == str(files[1])
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_base_indexer.py::TestPruneEndToEnd -v`
Expected: PASS

**Step 3: Run full check**

Run: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
Expected: All pass

**Step 4: Commit**

```bash
git add tests/test_base_indexer.py
git commit -m "test: add end-to-end pruning lifecycle test"
```
