"""Tests for the walk result processing pipeline."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.helpers import fake_embeddings, make_test_config
from ragling.config import Config
from ragling.document.chunker import Chunk
from ragling.indexers.walk_processor import process_walk_result
from ragling.indexers.walker import FileRoute, WalkResult, WalkStats


def _fake_parse_route(
    route: FileRoute,
    config: Config,
    doc_store: object,
    watch_root: Path,
) -> list[Chunk]:
    """Return a single chunk for any file that exists."""
    if not route.path.exists():
        msg = f"No such file: {route.path}"
        raise FileNotFoundError(msg)
    text = route.path.read_text()
    return [Chunk(text=text, title=route.path.name, metadata={}, chunk_index=0)]


def _make_config(tmp_path: Path) -> Config:
    return make_test_config(
        tmp_path,
        group_name="test",
        group_db_dir=tmp_path / "groups",
    )


def _setup_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a test database without sqlite-vec (not available on all platforms)."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            collection_type TEXT NOT NULL DEFAULT 'project',
            description TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            source_path TEXT NOT NULL,
            file_hash TEXT,
            file_modified_at TEXT,
            last_indexed_at TEXT,
            UNIQUE(collection_id, source_path)
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(source_id, chunk_index)
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        INSERT INTO meta (key, value) VALUES ('schema_version', '2');
    """)
    conn.commit()
    return conn


# All tests patch _parse_route (avoids needing Docling/HybridChunker) and
# upsert_source_with_chunks (avoids needing sqlite-vec).
_COMMON_PATCHES = [
    patch("ragling.indexers.walk_processor._parse_route", side_effect=_fake_parse_route),
    patch("ragling.indexers.walk_processor.get_embeddings", side_effect=fake_embeddings),
    patch("ragling.indexers.walk_processor.upsert_source_with_chunks", return_value=1),
    patch("ragling.indexers.walk_processor.prune_stale_sources", return_value=0),
]


def _apply_patches():
    """Start all common patches and return mock objects."""
    mocks = [p.start() for p in _COMMON_PATCHES]
    return mocks  # [parse_route, embeddings, upsert, prune]


@pytest.fixture(autouse=True)
def _common_mocks():
    """Apply common patches for all tests in this module."""
    for p in _COMMON_PATCHES:
        p.start()
    yield
    for p in _COMMON_PATCHES:
        p.stop()


class TestProcessWalkResult:
    """Tests for the walk result processor."""

    def test_indexes_markdown_file(self, tmp_path: Path) -> None:
        conn = _setup_db(tmp_path)

        root = tmp_path / "root"
        root.mkdir()
        md_file = root / "note.md"
        md_file.write_text("# Hello\n\nThis is a note.")

        walk_result = WalkResult(
            routes=[
                FileRoute(path=md_file, parser="markdown", git_root=None, vault_root=None),
            ],
            git_roots=set(),
            stats=WalkStats(by_parser={"markdown": 1}, directories=1),
        )

        config = _make_config(tmp_path)
        result = process_walk_result(
            walk_result,
            conn,
            config,
            watch_name="test-watch",
            watch_root=root,
        )

        assert result.indexed >= 1
        assert result.errors == 0

        # Verify collection was created
        row = conn.execute(
            "SELECT name FROM collections WHERE name = ?", ("test-watch",)
        ).fetchone()
        assert row is not None

    def test_skips_unchanged_files(self, tmp_path: Path) -> None:
        conn = _setup_db(tmp_path)

        root = tmp_path / "root"
        root.mkdir()
        md_file = root / "note.md"
        md_file.write_text("# Hello\n\nThis is a note.")

        walk_result = WalkResult(
            routes=[
                FileRoute(path=md_file, parser="markdown", git_root=None, vault_root=None),
            ],
            git_roots=set(),
            stats=WalkStats(by_parser={"markdown": 1}, directories=1),
        )

        config = _make_config(tmp_path)

        # First run: indexes
        result1 = process_walk_result(
            walk_result,
            conn,
            config,
            watch_name="test-watch",
            watch_root=root,
        )
        assert result1.indexed >= 1

        # Simulate the source existing in the DB with matching hash
        # (upsert was mocked, so we insert manually for change detection)
        from ragling.indexers.base import file_hash

        coll_id = conn.execute(
            "SELECT id FROM collections WHERE name = ?", ("test-watch",)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO sources (collection_id, source_type, source_path, file_hash) "
            "VALUES (?, ?, ?, ?)",
            (coll_id, "markdown", str(md_file), file_hash(md_file)),
        )
        conn.commit()

        # Second run: skips (file unchanged)
        result2 = process_walk_result(
            walk_result,
            conn,
            config,
            watch_name="test-watch",
            watch_root=root,
        )
        assert result2.skipped >= 1
        assert result2.indexed == 0

    def test_force_reindexes_unchanged(self, tmp_path: Path) -> None:
        conn = _setup_db(tmp_path)

        root = tmp_path / "root"
        root.mkdir()
        md_file = root / "note.md"
        md_file.write_text("# Hello")

        walk_result = WalkResult(
            routes=[
                FileRoute(path=md_file, parser="markdown", git_root=None, vault_root=None),
            ],
            git_roots=set(),
            stats=WalkStats(by_parser={"markdown": 1}, directories=1),
        )

        config = _make_config(tmp_path)

        # First run
        process_walk_result(
            walk_result,
            conn,
            config,
            watch_name="test-watch",
            watch_root=root,
        )

        # Simulate the source existing with matching hash
        from ragling.indexers.base import file_hash

        coll_id = conn.execute(
            "SELECT id FROM collections WHERE name = ?", ("test-watch",)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO sources (collection_id, source_type, source_path, file_hash) "
            "VALUES (?, ?, ?, ?)",
            (coll_id, "markdown", str(md_file), file_hash(md_file)),
        )
        conn.commit()

        # Force re-index — should still index even though hash matches
        result = process_walk_result(
            walk_result,
            conn,
            config,
            watch_name="test-watch",
            watch_root=root,
            force=True,
        )
        assert result.indexed >= 1

    def test_per_item_errors_dont_cascade(self, tmp_path: Path) -> None:
        """One bad file shouldn't stop others from being indexed."""
        conn = _setup_db(tmp_path)

        root = tmp_path / "root"
        root.mkdir()
        good = root / "good.md"
        good.write_text("# Good file")
        bad = root / "bad.md"
        bad.write_text("# Bad file")

        walk_result = WalkResult(
            routes=[
                FileRoute(path=good, parser="markdown", git_root=None, vault_root=None),
                FileRoute(path=bad, parser="markdown", git_root=None, vault_root=None),
            ],
            git_roots=set(),
            stats=WalkStats(by_parser={"markdown": 2}, directories=1),
        )

        config = _make_config(tmp_path)

        # Delete bad.md so it'll fail during processing
        bad.unlink()

        result = process_walk_result(
            walk_result,
            conn,
            config,
            watch_name="test-watch",
            watch_root=root,
        )
        # Good file should still be indexed
        assert result.indexed >= 1
        assert result.errors >= 1

    def test_treesitter_file_indexed(self, tmp_path: Path) -> None:
        conn = _setup_db(tmp_path)

        root = tmp_path / "root"
        root.mkdir()
        py_file = root / "main.py"
        py_file.write_text("def hello():\n    print('hello')\n")

        walk_result = WalkResult(
            routes=[
                FileRoute(path=py_file, parser="treesitter", git_root=root, vault_root=None),
            ],
            git_roots=set(),
            stats=WalkStats(by_parser={"treesitter": 1}, directories=1),
        )

        config = _make_config(tmp_path)

        result = process_walk_result(
            walk_result,
            conn,
            config,
            watch_name="test-watch",
            watch_root=root,
        )

        assert result.indexed >= 1
        assert result.errors == 0

    def test_total_found_matches_route_count(self, tmp_path: Path) -> None:
        conn = _setup_db(tmp_path)

        root = tmp_path / "root"
        root.mkdir()
        (root / "a.md").write_text("# A")
        (root / "b.md").write_text("# B")

        walk_result = WalkResult(
            routes=[
                FileRoute(path=root / "a.md", parser="markdown", git_root=None, vault_root=None),
                FileRoute(path=root / "b.md", parser="markdown", git_root=None, vault_root=None),
            ],
            git_roots=set(),
            stats=WalkStats(by_parser={"markdown": 2}, directories=1),
        )

        config = _make_config(tmp_path)
        result = process_walk_result(
            walk_result,
            conn,
            config,
            watch_name="test-watch",
            watch_root=root,
        )

        assert result.total_found == 2
        assert result.indexed == 2

    def test_collection_assignment_used(self, tmp_path: Path) -> None:
        """Verify that assign_collection determines the collection for each file."""
        conn = _setup_db(tmp_path)

        root = tmp_path / "root"
        root.mkdir()
        md_file = root / "note.md"
        md_file.write_text("# Note")

        walk_result = WalkResult(
            routes=[
                FileRoute(path=md_file, parser="markdown", git_root=None, vault_root=None),
            ],
            git_roots=set(),
            stats=WalkStats(by_parser={"markdown": 1}, directories=1),
        )

        config = _make_config(tmp_path)
        process_walk_result(
            walk_result,
            conn,
            config,
            watch_name="my-watch",
            watch_root=root,
        )

        # The collection should have been created with the watch_name
        row = conn.execute("SELECT name FROM collections WHERE name = ?", ("my-watch",)).fetchone()
        assert row is not None
