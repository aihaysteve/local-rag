"""Tests for ragling.indexers.base module -- delete and prune functions."""

import sqlite3
from pathlib import Path

from ragling.config import Config
from ragling.db import get_connection, init_db
from ragling.indexers.base import delete_source, prune_stale_sources, upsert_source_with_chunks


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

        result = delete_source(conn, cid, "/tmp/file.txt")

        assert result is True
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM vec_documents").fetchone()[0] == 0

    def test_noop_when_source_does_not_exist(self, tmp_path: Path) -> None:
        conn = _make_conn(tmp_path)
        from ragling.db import get_or_create_collection

        cid = get_or_create_collection(conn, "test-coll", "project")

        # Should not raise, returns False
        result = delete_source(conn, cid, "/tmp/nonexistent.txt")
        assert result is False

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
