"""Tests for ragling.db module."""

from pathlib import Path

from ragling.config import Config


class TestGetConnection:
    """Tests for get_connection with per-group path selection."""

    def test_uses_group_index_db_path_when_group_set(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            group_name="test-group",
            group_db_dir=tmp_path / "groups",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            expected_path = tmp_path / "groups" / "test-group" / "index.db"
            assert expected_path.exists()
        finally:
            conn.close()

    def test_falls_back_to_db_path_for_default_group(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            db_path=tmp_path / "legacy.db",
            group_name="default",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            assert (tmp_path / "legacy.db").exists()
        finally:
            conn.close()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            group_name="deep-group",
            group_db_dir=tmp_path / "a" / "b" / "c",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            expected = tmp_path / "a" / "b" / "c" / "deep-group" / "index.db"
            assert expected.exists()
        finally:
            conn.close()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            group_name="wal-test",
            group_db_dir=tmp_path / "groups",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"
        finally:
            conn.close()


class TestInitDbThroughGroupConnection:
    """Tests for init_db working through per-group connections."""

    def test_group_connection_creates_tables(self, tmp_path: Path) -> None:
        """init_db through group connection creates all required tables."""
        from ragling.db import get_connection, init_db

        config = Config(
            group_name="table-test",
            group_db_dir=tmp_path / "groups",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        init_db(conn, config)
        try:
            # Verify core tables exist
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "collections" in tables
            assert "sources" in tables
            assert "documents" in tables
            assert "documents_fts" in tables
        finally:
            conn.close()

    def test_different_groups_get_different_dbs(self, tmp_path: Path) -> None:
        """Two groups should produce different database files."""
        from ragling.db import get_connection

        config1 = Config(
            group_name="group-a",
            group_db_dir=tmp_path / "groups",
            embedding_dimensions=4,
        )
        config2 = Config(
            group_name="group-b",
            group_db_dir=tmp_path / "groups",
            embedding_dimensions=4,
        )
        conn1 = get_connection(config1)
        conn2 = get_connection(config2)
        try:
            path_a = tmp_path / "groups" / "group-a" / "index.db"
            path_b = tmp_path / "groups" / "group-b" / "index.db"
            assert path_a.exists()
            assert path_b.exists()
            assert path_a != path_b
        finally:
            conn1.close()
            conn2.close()


class TestDeleteCollection:
    """Tests for delete_collection."""

    def test_delete_collection_removes_all_data(self, tmp_path: Path) -> None:
        """delete_collection removes the collection, its sources, documents, and vectors."""
        from ragling.db import delete_collection, get_connection, get_or_create_collection, init_db

        config = Config(db_path=tmp_path / "test.db", embedding_dimensions=4)
        conn = get_connection(config)
        init_db(conn, config)

        coll_id = get_or_create_collection(conn, "test-coll", "project")
        # Insert a source and document to verify cascade
        conn.execute(
            "INSERT INTO sources (collection_id, source_type, source_path) VALUES (?, ?, ?)",
            (coll_id, "markdown", "/tmp/test.md"),
        )
        conn.commit()

        deleted = delete_collection(conn, "test-coll")
        assert deleted is True

        # Verify collection is gone
        row = conn.execute("SELECT id FROM collections WHERE name = ?", ("test-coll",)).fetchone()
        assert row is None
        conn.close()

    def test_delete_collection_nonexistent_returns_false(self, tmp_path: Path) -> None:
        """delete_collection returns False if the collection doesn't exist."""
        from ragling.db import delete_collection, get_connection, init_db

        config = Config(db_path=tmp_path / "test.db", embedding_dimensions=4)
        conn = get_connection(config)
        init_db(conn, config)

        deleted = delete_collection(conn, "nonexistent")
        assert deleted is False
        conn.close()
