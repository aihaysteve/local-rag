# tests/test_integration.py
"""Integration tests for ragling: multi-group sharing, cache reuse, and WAL concurrency.

Includes end-to-end pipeline tests exercising file → indexer → chunking →
embedding → DB → search → results.
"""

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


@requires_sqlite_extensions
class TestFullPipelineEndToEnd:
    """End-to-end test: file on disk -> ProjectIndexer -> chunking -> embedding -> DB -> search.

    Mocks only the embedding layer (Ollama) and the Docling-based chunking
    (heavy ML dependency). Uses real SQLite, real file system, and real
    ProjectIndexer / search code.
    """

    def test_index_and_search_text_file(self, tmp_path: Path) -> None:
        """Index a .txt file via ProjectIndexer, then find it via hybrid search."""
        from ragling.chunker import Chunk
        from ragling.config import Config
        from ragling.db import get_connection, init_db
        from ragling.indexers.project import ProjectIndexer
        from ragling.search import SearchResult, search

        # 1. Create a text file on disk
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        test_file = doc_dir / "notes.txt"
        test_file.write_text(
            "Photosynthesis is the process by which green plants "
            "convert sunlight into chemical energy."
        )

        # 2. Configure with small embedding dimensions for testing
        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )

        # 3. Set up real DB
        conn = get_connection(config)
        init_db(conn, config)

        # 4. Fixed embedding vectors
        fixed_embedding = [0.5, 0.3, 0.1, 0.8]

        # 5. Mock only embeddings and the Docling chunking path
        with (
            patch(
                "ragling.indexers.project._parse_and_chunk",
                return_value=[
                    Chunk(
                        text=(
                            "Photosynthesis is the process by which green plants "
                            "convert sunlight into chemical energy."
                        ),
                        title="notes.txt",
                        metadata={"source_path": str(test_file)},
                        chunk_index=0,
                    ),
                ],
            ),
            patch(
                "ragling.indexers.project.get_embeddings",
                return_value=[fixed_embedding],
            ),
        ):
            # 6. Run ProjectIndexer
            indexer = ProjectIndexer("test-collection", [doc_dir])
            result = indexer.index(conn, config)

        # Verify indexing succeeded
        assert result.indexed == 1
        assert result.errors == 0

        # 7. Verify data is in the database
        doc_row = conn.execute("SELECT content, title FROM documents").fetchone()
        assert doc_row is not None
        assert "Photosynthesis" in doc_row["content"]
        assert doc_row["title"] == "notes.txt"

        source_row = conn.execute("SELECT source_path, source_type FROM sources").fetchone()
        assert source_row is not None
        assert source_row["source_path"] == str(test_file.resolve())
        assert source_row["source_type"] == "plaintext"

        coll_row = conn.execute(
            "SELECT name, collection_type FROM collections WHERE name = ?",
            ("test-collection",),
        ).fetchone()
        assert coll_row is not None
        assert coll_row["collection_type"] == "project"

        # 8. Search and verify results
        results = search(
            conn=conn,
            query_embedding=fixed_embedding,
            query_text="photosynthesis plants sunlight",
            top_k=5,
            filters=None,
            config=config,
        )

        assert len(results) >= 1
        top_result = results[0]
        assert isinstance(top_result, SearchResult)
        assert "Photosynthesis" in top_result.content
        assert top_result.title == "notes.txt"
        assert top_result.collection == "test-collection"
        assert top_result.source_type == "plaintext"
        assert top_result.source_path == str(test_file.resolve())

        conn.close()

    def test_index_multiple_files_and_search(self, tmp_path: Path) -> None:
        """Index multiple files and verify search returns the most relevant one."""
        from ragling.chunker import Chunk
        from ragling.config import Config
        from ragling.db import get_connection, init_db
        from ragling.indexers.project import ProjectIndexer
        from ragling.search import search

        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()

        # Two files with different content
        file_a = doc_dir / "cooking.txt"
        file_a.write_text("Italian pasta recipes with tomato sauce and basil.")
        file_b = doc_dir / "astronomy.txt"
        file_b.write_text("The Andromeda galaxy is the nearest spiral galaxy.")

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )

        conn = get_connection(config)
        init_db(conn, config)

        # Give the cooking doc a vector closer to the query vector
        cooking_embedding = [0.9, 0.1, 0.0, 0.0]
        astronomy_embedding = [0.0, 0.0, 0.1, 0.9]
        query_embedding = [0.9, 0.1, 0.0, 0.0]  # close to cooking

        parse_calls: list[Path] = []

        def mock_parse_and_chunk(path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            parse_calls.append(path)
            if path.name == "cooking.txt":
                return [
                    Chunk(
                        text="Italian pasta recipes with tomato sauce and basil.",
                        title="cooking.txt",
                        metadata={"source_path": str(path)},
                        chunk_index=0,
                    )
                ]
            elif path.name == "astronomy.txt":
                return [
                    Chunk(
                        text="The Andromeda galaxy is the nearest spiral galaxy.",
                        title="astronomy.txt",
                        metadata={"source_path": str(path)},
                        chunk_index=0,
                    )
                ]
            return []

        embed_calls: list[list[str]] = []

        def mock_get_embeddings(texts: list[str], config):  # type: ignore[no-untyped-def]
            embed_calls.append(texts)
            embeddings = []
            for text in texts:
                if "pasta" in text.lower():
                    embeddings.append(cooking_embedding)
                else:
                    embeddings.append(astronomy_embedding)
            return embeddings

        with (
            patch(
                "ragling.indexers.project._parse_and_chunk",
                side_effect=mock_parse_and_chunk,
            ),
            patch(
                "ragling.indexers.project.get_embeddings",
                side_effect=mock_get_embeddings,
            ),
        ):
            indexer = ProjectIndexer("multi-docs", [doc_dir])
            result = indexer.index(conn, config)

        assert result.indexed == 2
        assert result.errors == 0

        # Verify both documents are in the DB
        doc_count = conn.execute("SELECT COUNT(*) AS cnt FROM documents").fetchone()["cnt"]
        assert doc_count == 2

        # Search with query embedding close to cooking
        results = search(
            conn=conn,
            query_embedding=query_embedding,
            query_text="pasta tomato cooking",
            top_k=5,
            filters=None,
            config=config,
        )

        assert len(results) == 2
        # The cooking doc should rank first (closer vector + FTS match)
        assert results[0].title == "cooking.txt"
        assert "pasta" in results[0].content.lower()

        conn.close()

    def test_reindex_updates_content(self, tmp_path: Path) -> None:
        """Re-indexing a modified file replaces old content in the DB."""
        from ragling.chunker import Chunk
        from ragling.config import Config
        from ragling.db import get_connection, init_db
        from ragling.indexers.project import ProjectIndexer
        from ragling.search import search

        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        test_file = doc_dir / "evolving.txt"
        test_file.write_text("Original content about quantum computing.")

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
            chunk_size_tokens=256,
        )

        conn = get_connection(config)
        init_db(conn, config)

        embedding = [0.5, 0.5, 0.0, 0.0]

        # First index
        with (
            patch(
                "ragling.indexers.project._parse_and_chunk",
                return_value=[
                    Chunk(
                        text="Original content about quantum computing.",
                        title="evolving.txt",
                        chunk_index=0,
                    ),
                ],
            ),
            patch(
                "ragling.indexers.project.get_embeddings",
                return_value=[embedding],
            ),
        ):
            indexer = ProjectIndexer("evolving-coll", [doc_dir])
            result1 = indexer.index(conn, config)

        assert result1.indexed == 1

        # Modify the file
        test_file.write_text("Updated content about machine learning.")

        # Re-index with force
        with (
            patch(
                "ragling.indexers.project._parse_and_chunk",
                return_value=[
                    Chunk(
                        text="Updated content about machine learning.",
                        title="evolving.txt",
                        chunk_index=0,
                    ),
                ],
            ),
            patch(
                "ragling.indexers.project.get_embeddings",
                return_value=[embedding],
            ),
        ):
            indexer2 = ProjectIndexer("evolving-coll", [doc_dir])
            result2 = indexer2.index(conn, config, force=True)

        assert result2.indexed == 1

        # Verify only the updated content is in the DB (no duplicates)
        docs = conn.execute("SELECT content FROM documents").fetchall()
        assert len(docs) == 1
        assert "machine learning" in docs[0]["content"]
        assert "quantum computing" not in docs[0]["content"]

        # Search should find updated content
        results = search(
            conn=conn,
            query_embedding=embedding,
            query_text="machine learning",
            top_k=5,
            filters=None,
            config=config,
        )

        assert len(results) >= 1
        assert "machine learning" in results[0].content

        conn.close()
