# tests/test_integration.py
"""Integration test for the full NanoBot RAG flow."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from ragling.config import Config, UserConfig

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
