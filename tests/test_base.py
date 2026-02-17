"""Tests for ragling.indexers.base module."""

import json
import sqlite3
from pathlib import Path

import pytest

from ragling.chunker import Chunk
from ragling.config import Config
from ragling.indexers.base import IndexResult, file_hash, upsert_source_with_chunks


class TestIndexResult:
    def test_skipped_empty_field_exists(self) -> None:
        result = IndexResult()
        assert hasattr(result, "skipped_empty")

    def test_skipped_empty_defaults_to_zero(self) -> None:
        result = IndexResult()
        assert result.skipped_empty == 0

    def test_skipped_empty_can_be_set(self) -> None:
        result = IndexResult(skipped_empty=5)
        assert result.skipped_empty == 5

    def test_str_includes_skipped_empty_when_nonzero(self) -> None:
        result = IndexResult(indexed=1, skipped=2, skipped_empty=3, errors=0, total_found=6)
        s = str(result)
        assert "skipped_empty" in s.lower() or "Skipped empty" in s
        assert "3" in s

    def test_str_omits_skipped_empty_when_zero(self) -> None:
        result = IndexResult(indexed=1, skipped=2, errors=0, total_found=3)
        s = str(result)
        assert "skipped_empty" not in s.lower()


class TestFileHash:
    def test_returns_sha256_hex(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h = file_hash(f)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("identical")
        b.write_text("identical")
        assert file_hash(a) == file_hash(b)

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("one")
        b.write_text("two")
        assert file_hash(a) != file_hash(b)


@pytest.fixture()
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a real SQLite DB with full schema for testing."""
    from ragling.db import get_connection, init_db

    config = Config(
        group_name="test",
        group_db_dir=tmp_path / "groups",
        embedding_dimensions=4,
    )
    conn = get_connection(config)
    init_db(conn, config)
    # Create a test collection
    conn.execute("INSERT INTO collections (name, collection_type) VALUES ('test-coll', 'project')")
    conn.commit()
    yield conn
    conn.close()


def _coll_id(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT id FROM collections WHERE name = 'test-coll'").fetchone()["id"]


def _make_chunks(n: int = 1) -> list[Chunk]:
    return [
        Chunk(text=f"chunk {i}", title="doc", metadata={"idx": i}, chunk_index=i) for i in range(n)
    ]


def _make_embeddings(n: int = 1) -> list[list[float]]:
    return [[float(i) * 0.1, 0.2, 0.3, 0.4] for i in range(n)]


class TestUpsertSourceWithChunks:
    def test_inserts_new_source(self, db_conn: sqlite3.Connection) -> None:
        cid = _coll_id(db_conn)
        source_id = upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path="/test/file.txt",
            source_type="plaintext",
            chunks=_make_chunks(2),
            embeddings=_make_embeddings(2),
            file_hash="abc123",
        )
        row = db_conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        assert row["source_path"] == "/test/file.txt"
        assert row["file_hash"] == "abc123"
        docs = db_conn.execute(
            "SELECT * FROM documents WHERE source_id = ? ORDER BY chunk_index", (source_id,)
        ).fetchall()
        assert len(docs) == 2
        assert docs[0]["content"] == "chunk 0"
        assert docs[1]["content"] == "chunk 1"

    def test_updates_existing_source_with_hash(self, db_conn: sqlite3.Connection) -> None:
        cid = _coll_id(db_conn)
        sid1 = upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path="/test/file.txt",
            source_type="plaintext",
            chunks=_make_chunks(1),
            embeddings=_make_embeddings(1),
            file_hash="old_hash",
        )
        sid2 = upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path="/test/file.txt",
            source_type="markdown",
            chunks=_make_chunks(3),
            embeddings=_make_embeddings(3),
            file_hash="new_hash",
        )
        # Same source_id reused
        assert sid1 == sid2
        # Source updated
        row = db_conn.execute("SELECT * FROM sources WHERE id = ?", (sid1,)).fetchone()
        assert row["file_hash"] == "new_hash"
        assert row["source_type"] == "markdown"
        # Old docs replaced with new
        docs = db_conn.execute("SELECT * FROM documents WHERE source_id = ?", (sid1,)).fetchall()
        assert len(docs) == 3

    def test_cleans_up_old_vectors(self, db_conn: sqlite3.Connection) -> None:
        cid = _coll_id(db_conn)
        sid = upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path="/test/file.txt",
            source_type="plaintext",
            chunks=_make_chunks(2),
            embeddings=_make_embeddings(2),
        )
        old_doc_ids = [
            r["id"]
            for r in db_conn.execute(
                "SELECT id FROM documents WHERE source_id = ?", (sid,)
            ).fetchall()
        ]
        # Re-upsert with different chunks
        upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path="/test/file.txt",
            source_type="plaintext",
            chunks=_make_chunks(1),
            embeddings=_make_embeddings(1),
        )
        # Old vectors should be gone
        for old_id in old_doc_ids:
            vec = db_conn.execute(
                "SELECT * FROM vec_documents WHERE document_id = ?", (old_id,)
            ).fetchone()
            assert vec is None

    def test_without_file_hash_only_updates_timestamp(self, db_conn: sqlite3.Connection) -> None:
        cid = _coll_id(db_conn)
        sid = upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path="msg-123",
            source_type="email",
            chunks=_make_chunks(1),
            embeddings=_make_embeddings(1),
            file_hash="first_hash",
        )
        row_before = db_conn.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone()
        # Re-upsert without file_hash (email/RSS pattern)
        upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path="msg-123",
            source_type="email",
            chunks=_make_chunks(1),
            embeddings=_make_embeddings(1),
        )
        row_after = db_conn.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone()
        # file_hash preserved from original insert
        assert row_after["file_hash"] == "first_hash"
        # last_indexed_at updated
        assert row_after["last_indexed_at"] >= row_before["last_indexed_at"]

    def test_metadata_serialized_to_json(self, db_conn: sqlite3.Connection) -> None:
        cid = _coll_id(db_conn)
        chunks = [Chunk(text="hi", title="t", metadata={"sender": "a@b.com"}, chunk_index=0)]
        sid = upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path="/test",
            source_type="email",
            chunks=chunks,
            embeddings=_make_embeddings(1),
        )
        doc = db_conn.execute(
            "SELECT metadata FROM documents WHERE source_id = ?", (sid,)
        ).fetchone()
        meta = json.loads(doc["metadata"])
        assert meta["sender"] == "a@b.com"

    def test_empty_metadata_stored_as_null(self, db_conn: sqlite3.Connection) -> None:
        cid = _coll_id(db_conn)
        chunks = [Chunk(text="hi", title="t", metadata={}, chunk_index=0)]
        sid = upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path="/test",
            source_type="plaintext",
            chunks=chunks,
            embeddings=_make_embeddings(1),
        )
        doc = db_conn.execute(
            "SELECT metadata FROM documents WHERE source_id = ?", (sid,)
        ).fetchone()
        assert doc["metadata"] is None

    def test_two_pass_indexing_no_duplicates(self, db_conn: sqlite3.Connection) -> None:
        """Re-indexing a file (e.g., from two-pass git+document scan) produces no duplicates."""
        cid = _coll_id(db_conn)
        path = "/repo/docs/spec.md"

        # First pass: indexed as markdown with initial content
        sid1 = upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path=path,
            source_type="markdown",
            chunks=_make_chunks(2),
            embeddings=_make_embeddings(2),
            file_hash="hash_v1",
        )

        # Second pass: same file re-indexed (simulates two-pass scan)
        sid2 = upsert_source_with_chunks(
            db_conn,
            collection_id=cid,
            source_path=path,
            source_type="markdown",
            chunks=_make_chunks(3),
            embeddings=_make_embeddings(3),
            file_hash="hash_v1",
        )

        # Same source ID reused
        assert sid1 == sid2

        # Exactly one source row
        sources = db_conn.execute(
            "SELECT * FROM sources WHERE collection_id = ? AND source_path = ?",
            (cid, path),
        ).fetchall()
        assert len(sources) == 1

        # Documents replaced, not duplicated — should have 3 (from second pass)
        docs = db_conn.execute("SELECT * FROM documents WHERE source_id = ?", (sid1,)).fetchall()
        assert len(docs) == 3

        # Vectors match document count
        vec_count = db_conn.execute(
            "SELECT COUNT(*) as cnt FROM vec_documents WHERE document_id IN "
            "(SELECT id FROM documents WHERE source_id = ?)",
            (sid1,),
        ).fetchone()["cnt"]
        assert vec_count == 3
