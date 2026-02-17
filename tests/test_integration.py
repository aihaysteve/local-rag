# tests/test_integration.py
"""Integration tests for ragling: multi-group sharing, cache reuse, and WAL concurrency."""

import sqlite3
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ragling.config import Config, UserConfig
from ragling.doc_store import DocStore

# Skip if sqlite-vec not available
_conn = sqlite3.connect(":memory:")
_has_load_extension = hasattr(_conn, "enable_load_extension")
_conn.close()

requires_sqlite_extensions = pytest.mark.skipif(
    not _has_load_extension,
    reason="sqlite3 was not compiled with loadable extension support",
)


@requires_sqlite_extensions
class TestFullFlow:
    """End-to-end test: config -> index -> search with user scoping."""

    def test_user_sees_own_and_global_content_only(self, tmp_path: Path) -> None:
        """Kitchen user searches and sees kitchen + global docs, not garage docs."""
        # Setup directories
        home = tmp_path / "groups"
        global_dir = tmp_path / "global"
        (home / "kitchen").mkdir(parents=True)
        (home / "garage").mkdir(parents=True)
        global_dir.mkdir()

        # Create files
        (home / "kitchen" / "recipe.md").write_text("# Pasta Recipe\n\nCook the pasta.")
        (home / "garage" / "tools.md").write_text("# Garage Tools\n\nHammer and nails.")
        (global_dir / "rules.md").write_text("# House Rules\n\nBe kind to each other.")

        # Config
        config = Config(
            home=home,
            global_paths=[global_dir],
            users={
                "kitchen": UserConfig(api_key="rag_kitchen"),
                "garage": UserConfig(api_key="rag_garage"),
            },
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        # Mock embeddings (return fixed 4d vectors)
        mock_embeddings = [[1.0, 0.0, 0.0, 0.0]]

        with patch("ragling.embeddings.get_embeddings", return_value=mock_embeddings):
            with patch("ragling.embeddings.get_embedding", return_value=[1.0, 0.0, 0.0, 0.0]):
                from ragling.auth import resolve_api_key
                from ragling.chunker import Chunk
                from ragling.db import get_connection, get_or_create_collection, init_db
                from ragling.indexers.base import upsert_source_with_chunks
                from ragling.search import search

                conn = get_connection(config)
                init_db(conn, config)

                # Index kitchen file
                kitchen_id = get_or_create_collection(conn, "kitchen", "project")
                upsert_source_with_chunks(
                    conn,
                    collection_id=kitchen_id,
                    source_path=str(home / "kitchen" / "recipe.md"),
                    source_type="markdown",
                    chunks=[Chunk(text="Cook the pasta.", title="Pasta Recipe", chunk_index=0)],
                    embeddings=[[1.0, 0.0, 0.0, 0.0]],
                    file_hash="abc123",
                )

                # Index garage file
                garage_id = get_or_create_collection(conn, "garage", "project")
                upsert_source_with_chunks(
                    conn,
                    collection_id=garage_id,
                    source_path=str(home / "garage" / "tools.md"),
                    source_type="markdown",
                    chunks=[Chunk(text="Hammer and nails.", title="Garage Tools", chunk_index=0)],
                    embeddings=[[0.9, 0.1, 0.0, 0.0]],
                    file_hash="def456",
                )

                # Index global file
                global_id = get_or_create_collection(conn, "global", "project")
                upsert_source_with_chunks(
                    conn,
                    collection_id=global_id,
                    source_path=str(global_dir / "rules.md"),
                    source_type="markdown",
                    chunks=[
                        Chunk(
                            text="Be kind to each other.",
                            title="House Rules",
                            chunk_index=0,
                        )
                    ],
                    embeddings=[[0.8, 0.2, 0.0, 0.0]],
                    file_hash="ghi789",
                )

                # Resolve kitchen user
                user_ctx = resolve_api_key("rag_kitchen", config)
                assert user_ctx is not None
                visible = user_ctx.visible_collections(global_collection="global")

                # Search as kitchen user
                results = search(
                    conn=conn,
                    query_embedding=[1.0, 0.0, 0.0, 0.0],
                    query_text="pasta tools rules",
                    top_k=10,
                    filters=None,
                    config=config,
                    visible_collections=visible,
                )

                collections_in_results = {r.collection for r in results}
                assert "kitchen" in collections_in_results
                assert "global" in collections_in_results
                assert "garage" not in collections_in_results

                conn.close()


@requires_sqlite_extensions
class TestMultiGroupDocSharing:
    """Verify shared doc_store with per-group vector indexes."""

    def test_two_groups_share_doc_store_with_separate_indexes(self, tmp_path: Path) -> None:
        """Index same doc in two groups: one doc_store entry, two separate index DBs."""
        shared_db = tmp_path / "doc_store.sqlite"
        group_db_dir = tmp_path / "groups"

        # Create a test document
        doc = tmp_path / "report.txt"
        doc.write_text("Quarterly earnings report with detailed analysis.")

        converter = MagicMock(return_value={"text": "converted report"})
        store = DocStore(shared_db)

        # Both groups convert through the same shared store
        result_alpha = store.get_or_convert(doc, converter)
        result_beta = store.get_or_convert(doc, converter)

        # Converter called only once — second group gets cache hit
        assert converter.call_count == 1
        assert result_alpha == result_beta

        # Shared doc_store has exactly one source entry
        sources = store.list_sources()
        assert len(sources) == 1
        assert sources[0]["source_path"] == str(doc)

        # Per-group index DBs are at separate paths
        config_alpha = Config(
            group_name="alpha",
            group_db_dir=group_db_dir,
            shared_db_path=shared_db,
            embedding_dimensions=4,
        )
        config_beta = Config(
            group_name="beta",
            group_db_dir=group_db_dir,
            shared_db_path=shared_db,
            embedding_dimensions=4,
        )

        assert config_alpha.group_index_db_path != config_beta.group_index_db_path
        assert "alpha" in str(config_alpha.group_index_db_path)
        assert "beta" in str(config_beta.group_index_db_path)

        # Create actual per-group index DBs to confirm isolation
        from ragling.db import get_connection, init_db

        conn_alpha = get_connection(config_alpha)
        init_db(conn_alpha, config_alpha)
        conn_beta = get_connection(config_beta)
        init_db(conn_beta, config_beta)

        # Verify they are distinct files
        assert config_alpha.group_index_db_path.exists()
        assert config_beta.group_index_db_path.exists()
        assert config_alpha.group_index_db_path != config_beta.group_index_db_path

        conn_alpha.close()
        conn_beta.close()
        store.close()


class TestCacheReuseAcrossGroups:
    """Verify DocStore cache reuse when re-indexing in a new group."""

    def test_reindex_new_group_hits_cache(self, tmp_path: Path) -> None:
        """Re-indexing same documents in a new group does not re-convert."""
        shared_db = tmp_path / "doc_store.sqlite"
        store = DocStore(shared_db)

        # Create test files
        files = []
        for i in range(3):
            p = tmp_path / f"doc{i}.md"
            p.write_text(f"Document {i} content with some detail.")
            files.append(p)

        converter = MagicMock(side_effect=lambda p: {"text": f"converted {p.name}"})

        # "Group alpha" indexes all files — 3 converter calls
        for f in files:
            store.get_or_convert(f, converter)
        assert converter.call_count == 3

        # "Group beta" indexes the same files — 0 additional converter calls
        for f in files:
            store.get_or_convert(f, converter)
        assert converter.call_count == 3  # still 3, no new conversions

        store.close()


class TestFileModificationReindex:
    """Verify re-indexing after file modification replaces cached conversion."""

    def test_modified_file_triggers_reconversion(self, tmp_path: Path) -> None:
        """Modify a file, re-index, verify new conversion replaces old."""
        shared_db = tmp_path / "doc_store.sqlite"
        store = DocStore(shared_db)

        doc = tmp_path / "notes.md"
        doc.write_text("Original content of the document.")

        converter = MagicMock(side_effect=lambda p: {"text": p.read_text()})

        # Initial conversion
        result1 = store.get_or_convert(doc, converter)
        assert result1 == {"text": "Original content of the document."}
        assert converter.call_count == 1

        # Modify the file
        doc.write_text("Updated content with new information.")

        # Re-index — should detect hash change and re-convert
        result2 = store.get_or_convert(doc, converter)
        assert result2 == {"text": "Updated content with new information."}
        assert converter.call_count == 2

        # Cached version is the new one
        cached = store.get_document(str(doc))
        assert cached == {"text": "Updated content with new information."}

        # Source list still has exactly one entry (updated, not duplicated)
        sources = store.list_sources()
        assert len(sources) == 1

        store.close()


class TestConcurrentWALReads:
    """Verify WAL mode allows concurrent reads without blocking."""

    def test_multiple_readers_dont_block(self, tmp_path: Path) -> None:
        """Multiple connections can read the doc_store simultaneously via WAL."""
        shared_db = tmp_path / "doc_store.sqlite"
        store = DocStore(shared_db)

        # Populate with test data
        for i in range(5):
            p = tmp_path / f"file{i}.txt"
            p.write_text(f"Content {i}")
            store.get_or_convert(p, lambda path: {"text": path.read_text()})

        store.close()

        # Open multiple concurrent readers
        results: list[list[dict]] = []
        errors: list[Exception] = []

        def read_sources() -> None:
            try:
                reader = DocStore(shared_db)
                sources = reader.list_sources()
                results.append(sources)
                reader.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_sources) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Concurrent reads failed: {errors}"
        assert len(results) == 5
        for source_list in results:
            assert len(source_list) == 5
