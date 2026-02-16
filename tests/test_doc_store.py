"""Tests for ragling.doc_store module."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ragling.doc_store import DocStore


@pytest.fixture
def store(tmp_path: Path) -> DocStore:
    """Create a DocStore in a temp directory."""
    db_path = tmp_path / "doc_store.sqlite"
    return DocStore(db_path)


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    """Create a sample text file."""
    p = tmp_path / "sample.txt"
    p.write_text("Hello, world!")
    return p


class TestDocStoreInit:
    """Tests for DocStore initialization."""

    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "doc_store.sqlite"
        assert not db_path.exists()
        DocStore(db_path)
        assert db_path.exists()

    def test_creates_tables(self, store: DocStore) -> None:
        conn = sqlite3.connect(str(store._db_path))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "sources" in tables
        assert "converted_documents" in tables

    def test_enables_wal_mode(self, store: DocStore) -> None:
        conn = sqlite3.connect(str(store._db_path))
        row = conn.execute("PRAGMA journal_mode").fetchone()
        conn.close()
        assert row[0] == "wal"


class TestGetOrConvert:
    """Tests for get_or_convert."""

    def test_cache_miss_calls_converter(self, store: DocStore, sample_file: Path) -> None:
        converter = MagicMock(return_value={"text": "converted content"})
        result = store.get_or_convert(sample_file, converter)
        converter.assert_called_once_with(sample_file)
        assert result == {"text": "converted content"}

    def test_cache_hit_skips_converter(self, store: DocStore, sample_file: Path) -> None:
        converter = MagicMock(return_value={"text": "converted content"})
        result1 = store.get_or_convert(sample_file, converter)
        result2 = store.get_or_convert(sample_file, converter)
        assert converter.call_count == 1
        assert result1 == result2

    def test_file_change_triggers_reconversion(self, store: DocStore, sample_file: Path) -> None:
        converter = MagicMock(side_effect=[{"v": 1}, {"v": 2}])
        result1 = store.get_or_convert(sample_file, converter)
        assert result1 == {"v": 1}

        # Modify the file
        sample_file.write_text("Changed content!")

        result2 = store.get_or_convert(sample_file, converter)
        assert converter.call_count == 2
        assert result2 == {"v": 2}

    def test_stores_conversion_metadata(self, store: DocStore, sample_file: Path) -> None:
        converter = MagicMock(return_value={"text": "data"})
        store.get_or_convert(sample_file, converter)
        sources = store.list_sources()
        assert len(sources) == 1
        assert sources[0]["source_path"] == str(sample_file)
        assert sources[0]["content_hash"] is not None
        assert len(sources[0]["content_hash"]) == 64  # SHA-256 hex length


class TestGetDocument:
    """Tests for get_document."""

    def test_returns_none_for_unknown_path(self, store: DocStore) -> None:
        result = store.get_document("/nonexistent/file.txt")
        assert result is None

    def test_returns_cached_document(self, store: DocStore, sample_file: Path) -> None:
        converter = MagicMock(return_value={"text": "cached data"})
        store.get_or_convert(sample_file, converter)
        result = store.get_document(str(sample_file))
        assert result == {"text": "cached data"}


class TestInvalidate:
    """Tests for invalidate."""

    def test_removes_cached_conversion(self, store: DocStore, sample_file: Path) -> None:
        converter = MagicMock(return_value={"text": "data"})
        store.get_or_convert(sample_file, converter)
        assert store.get_document(str(sample_file)) is not None

        store.invalidate(str(sample_file))
        assert store.get_document(str(sample_file)) is None

    def test_invalidate_nonexistent_is_noop(self, store: DocStore) -> None:
        # Should not raise any exception
        store.invalidate("/nonexistent/file.txt")


class TestListSources:
    """Tests for list_sources."""

    def test_empty_store_returns_empty(self, store: DocStore) -> None:
        assert store.list_sources() == []

    def test_lists_all_sources(self, store: DocStore, tmp_path: Path) -> None:
        converter = MagicMock(return_value={"text": "data"})
        files = []
        for i in range(3):
            p = tmp_path / f"file{i}.txt"
            p.write_text(f"Content {i}")
            files.append(p)

        for f in files:
            store.get_or_convert(f, converter)

        sources = store.list_sources()
        assert len(sources) == 3
        source_paths = {s["source_path"] for s in sources}
        for f in files:
            assert str(f) in source_paths


class TestConfigHashCaching:
    """Tests for config_hash-aware caching."""

    def test_same_config_hash_is_cache_hit(self, store: DocStore, sample_file: Path) -> None:
        converter = MagicMock(return_value={"text": "data"})
        store.get_or_convert(sample_file, converter, config_hash="abc123")
        store.get_or_convert(sample_file, converter, config_hash="abc123")
        assert converter.call_count == 1

    def test_different_config_hash_triggers_reconversion(
        self, store: DocStore, sample_file: Path
    ) -> None:
        converter = MagicMock(side_effect=[{"v": 1}, {"v": 2}])
        r1 = store.get_or_convert(sample_file, converter, config_hash="old_hash")
        r2 = store.get_or_convert(sample_file, converter, config_hash="new_hash")
        assert converter.call_count == 2
        assert r1 == {"v": 1}
        assert r2 == {"v": 2}

    def test_empty_config_hash_is_valid(self, store: DocStore, sample_file: Path) -> None:
        converter = MagicMock(return_value={"text": "data"})
        result = store.get_or_convert(sample_file, converter, config_hash="")
        assert result == {"text": "data"}

    def test_backwards_compatible_without_config_hash(
        self, store: DocStore, sample_file: Path
    ) -> None:
        """Calling without config_hash still works (defaults to empty string)."""
        converter = MagicMock(return_value={"text": "data"})
        result = store.get_or_convert(sample_file, converter)
        assert result == {"text": "data"}


class TestMigrateConfigHash:
    """Tests for _migrate_config_hash upgrade path."""

    def test_adds_config_hash_column_if_missing(self, tmp_path: Path) -> None:
        """Opening a DB without config_hash column should add it automatically."""
        db_path = tmp_path / "legacy_store.sqlite"

        # Create a legacy DB without config_hash column
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                file_size INTEGER,
                file_modified_at TEXT,
                discovered_at TEXT DEFAULT (datetime('now')),
                UNIQUE(source_path)
            );
            CREATE TABLE IF NOT EXISTS converted_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                content_hash TEXT NOT NULL,
                docling_json TEXT NOT NULL,
                format TEXT NOT NULL,
                page_count INTEGER,
                conversion_time_ms INTEGER,
                converted_at TEXT DEFAULT (datetime('now')),
                UNIQUE(source_id, content_hash)
            );
        """)
        conn.commit()

        # Verify config_hash column does NOT exist
        cols = {row[1] for row in conn.execute("PRAGMA table_info(converted_documents)").fetchall()}
        assert "config_hash" not in cols
        conn.close()

        # Open with DocStore — migration should add the column
        store = DocStore(db_path)

        # Verify config_hash column now exists
        inner_conn = sqlite3.connect(str(db_path))
        cols = {
            row[1]
            for row in inner_conn.execute("PRAGMA table_info(converted_documents)").fetchall()
        }
        inner_conn.close()
        store.close()

        assert "config_hash" in cols
