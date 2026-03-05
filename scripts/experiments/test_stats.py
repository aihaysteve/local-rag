"""Tests for the rag_stats MCP tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from ragling.config import Config


def _make_config(tmp_path: Path, users: dict | None = None) -> Config:
    """Build a minimal Config pointing at a temp directory."""
    kwargs: dict[str, Any] = {
        "db_path": tmp_path / "test.db",
        "shared_db_path": tmp_path / "doc_store.sqlite",
        "embedding_dimensions": 4,
        "obsidian_vaults": (tmp_path / "vault",),
    }
    if users is not None:
        kwargs["users"] = users
    (tmp_path / "vault").mkdir(exist_ok=True)
    return Config(**kwargs)


def _seed_db(tmp_path: Path, config: Config) -> None:
    """Insert test collections and sources into the database."""
    from ragling.db import get_connection, init_db

    conn = get_connection(config)
    init_db(conn, config)

    # Insert collections
    conn.execute(
        "INSERT OR IGNORE INTO collections (name, collection_type) VALUES (?, ?)",
        ("obsidian", "system"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO collections (name, collection_type) VALUES (?, ?)",
        ("email", "system"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO collections (name, collection_type) VALUES (?, ?)",
        ("my-project", "project"),
    )

    # Insert sources for obsidian (2 sources, 5 chunks, last_indexed 2024-01-02)
    conn.execute(
        """
        INSERT INTO sources (collection_id, source_type, source_path, last_indexed_at)
        SELECT id, 'markdown', '/vault/note1.md', '2024-01-02T10:00:00'
        FROM collections WHERE name = 'obsidian'
        """,
    )
    conn.execute(
        """
        INSERT INTO sources (collection_id, source_type, source_path, last_indexed_at)
        SELECT id, 'markdown', '/vault/note2.md', '2024-01-01T08:00:00'
        FROM collections WHERE name = 'obsidian'
        """,
    )

    # Insert sources for email (1 source, 3 chunks, last_indexed 2024-02-15)
    conn.execute(
        """
        INSERT INTO sources (collection_id, source_type, source_path, last_indexed_at)
        SELECT id, 'email', '/email/1', '2024-02-15T12:00:00'
        FROM collections WHERE name = 'email'
        """,
    )

    # Insert chunks (documents) — no embeddings needed for stats queries
    for i in range(5):
        conn.execute(
            """
            INSERT INTO documents (source_id, collection_id, chunk_index, title, content)
            SELECT s.id, s.collection_id, ?, 'Note', 'content'
            FROM sources s
            JOIN collections c ON c.id = s.collection_id
            WHERE c.name = 'obsidian' AND s.source_path = '/vault/note1.md'
            """,
            (i,),
        )

    for i in range(3):
        conn.execute(
            """
            INSERT INTO documents (source_id, collection_id, chunk_index, title, content)
            SELECT s.id, s.collection_id, ?, 'Email', 'content'
            FROM sources s
            JOIN collections c ON c.id = s.collection_id
            WHERE c.name = 'email'
            """,
            (i,),
        )

    conn.commit()
    conn.close()


class TestStatsBasic:
    """Basic correctness tests for rag_stats."""

    def test_returns_total_collections(self, tmp_path: Path) -> None:
        """total_collections counts all collections in the DB."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        assert result["total_collections"] == 3

    def test_returns_total_sources(self, tmp_path: Path) -> None:
        """total_sources sums sources across all collections."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        # 2 obsidian + 1 email = 3 sources; my-project has none
        assert result["total_sources"] == 3

    def test_returns_total_chunks(self, tmp_path: Path) -> None:
        """total_chunks sums documents (chunks) across all collections."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        # 5 obsidian + 3 email = 8 chunks
        assert result["total_chunks"] == 8

    def test_returns_per_collection_stats(self, tmp_path: Path) -> None:
        """collections array contains per-collection stats."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        collections = result["collections"]
        assert len(collections) == 3

        # Find obsidian collection
        obsidian = next(c for c in collections if c["name"] == "obsidian")
        assert obsidian["collection_type"] == "system"
        assert obsidian["source_count"] == 2
        assert obsidian["chunk_count"] == 5
        assert obsidian["last_indexed"] == "2024-01-02T10:00:00"

        # Find email collection
        email = next(c for c in collections if c["name"] == "email")
        assert email["collection_type"] == "system"
        assert email["source_count"] == 1
        assert email["chunk_count"] == 3
        assert email["last_indexed"] == "2024-02-15T12:00:00"

        # Find my-project collection
        my_project = next(c for c in collections if c["name"] == "my-project")
        assert my_project["collection_type"] == "project"
        assert my_project["source_count"] == 0
        assert my_project["chunk_count"] == 0
        assert my_project["last_indexed"] is None

    def test_per_collection_last_indexed_is_max_in_collection(self, tmp_path: Path) -> None:
        """last_indexed for a collection is the MAX timestamp in that collection."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        collections = result["collections"]
        obsidian = next(c for c in collections if c["name"] == "obsidian")

        # Obsidian has two sources with 2024-01-02T10:00:00 and 2024-01-01T08:00:00
        # The max is 2024-01-02T10:00:00
        assert obsidian["last_indexed"] == "2024-01-02T10:00:00"

    def test_empty_database(self, tmp_path: Path) -> None:
        """All counts are zero and collections list is empty when the DB is empty."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        assert result["total_collections"] == 0
        assert result["total_sources"] == 0
        assert result["total_chunks"] == 0
        assert result["collections"] == []

    def test_collections_ordered_by_name(self, tmp_path: Path) -> None:
        """Collections are returned in alphabetical order by name."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        collections = result["collections"]
        names = [c["name"] for c in collections]

        # Should be ordered: email, my-project, obsidian
        assert names == ["email", "my-project", "obsidian"]


class TestStatsVisibility:
    """Visibility filtering: stats must only include user-visible collections."""

    def _setup_server(self, tmp_path: Path, user_collections: list[str]) -> tuple[Any, Any]:
        """Return (server, tools_dict) with seeded DB and authenticated user."""
        from ragling.config import UserConfig
        from ragling.mcp_server import create_server

        config = _make_config(
            tmp_path,
            users={
                "alice": UserConfig(
                    api_key="alice-key",
                    system_collections=user_collections,
                ),
            },
        )
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        tools = server._tool_manager._tools
        return server, tools

    def test_authenticated_user_sees_only_their_collections(self, tmp_path: Path) -> None:
        """Authenticated alice only sees obsidian (her system) + alice (own name)."""
        _server, tools = self._setup_server(tmp_path, user_collections=["obsidian"])
        fn = tools["rag_stats"].fn

        mock_token = MagicMock()
        mock_token.client_id = "alice"
        with patch("ragling.tools.helpers.get_access_token", return_value=mock_token):
            result = fn()

        # alice sees: "alice" (own collection, not in DB but visibly allowed)
        # + "obsidian" (system_collections). Email and my-project are excluded.
        # total_collections counts only what's in the DB AND visible.
        # "alice" collection is not in DB, so only obsidian is counted.
        assert result["total_collections"] == 1
        # 2 obsidian sources only
        assert result["total_sources"] == 2
        # 5 obsidian chunks only
        assert result["total_chunks"] == 5

        # Collections list should contain only obsidian
        collections = result["collections"]
        assert len(collections) == 1
        assert collections[0]["name"] == "obsidian"
        assert collections[0]["source_count"] == 2
        assert collections[0]["chunk_count"] == 5

    def test_authenticated_user_filters_per_collection_stats(self, tmp_path: Path) -> None:
        """Per-collection stats are filtered by visibility."""
        _server, tools = self._setup_server(tmp_path, user_collections=["obsidian"])
        fn = tools["rag_stats"].fn

        mock_token = MagicMock()
        mock_token.client_id = "alice"
        with patch("ragling.tools.helpers.get_access_token", return_value=mock_token):
            result = fn()

        # Only obsidian is visible
        collections = result["collections"]
        names = [c["name"] for c in collections]
        assert "obsidian" in names
        assert "email" not in names
        assert "my-project" not in names

    def test_unauthenticated_sees_all_collections(self, tmp_path: Path) -> None:
        """Without auth, all collections are included in stats."""
        _server, tools = self._setup_server(tmp_path, user_collections=["obsidian"])
        fn = tools["rag_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        assert result["total_collections"] == 3
        assert result["total_sources"] == 3
        assert result["total_chunks"] == 8

        # All collections in the response
        collections = result["collections"]
        assert len(collections) == 3
        names = [c["name"] for c in collections]
        assert set(names) == {"obsidian", "email", "my-project"}

    def test_unauthenticated_sees_complete_per_collection_stats(self, tmp_path: Path) -> None:
        """Unauthenticated users get stats for all collections."""
        _server, tools = self._setup_server(tmp_path, user_collections=["obsidian"])
        fn = tools["rag_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        collections = result["collections"]

        # Verify each collection has complete stats
        obsidian = next(c for c in collections if c["name"] == "obsidian")
        assert obsidian["source_count"] == 2
        assert obsidian["chunk_count"] == 5

        email = next(c for c in collections if c["name"] == "email")
        assert email["source_count"] == 1
        assert email["chunk_count"] == 3


class TestStatsRegistration:
    """Verify the tool is properly registered via register_all_tools."""

    def test_tool_is_registered_in_server(self, tmp_path: Path) -> None:
        """rag_stats appears in the server tool manager."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        server = create_server(group_name="default", config=config)
        assert "rag_stats" in server._tool_manager._tools

    def test_register_function_exists(self) -> None:
        """stats module exposes a register() callable."""
        from ragling.tools import stats

        assert callable(stats.register)
