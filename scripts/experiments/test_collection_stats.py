"""Tests for the rag_collection_stats MCP tool."""

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


class TestCollectionStatsBasic:
    """Basic correctness tests for rag_collection_stats."""

    def test_returns_total_collections(self, tmp_path: Path) -> None:
        """total_collections counts all collections in the DB."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_collection_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        assert result["total_collections"] == 3

    def test_returns_total_sources(self, tmp_path: Path) -> None:
        """total_sources sums sources across all collections."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_collection_stats"].fn

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
        fn = server._tool_manager._tools["rag_collection_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        # 5 obsidian + 3 email = 8 chunks
        assert result["total_chunks"] == 8

    def test_collections_by_type(self, tmp_path: Path) -> None:
        """collections_by_type groups collections by their type."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_collection_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        by_type = result["collections_by_type"]
        assert by_type["system"] == 2  # obsidian + email
        assert by_type["project"] == 1  # my-project

    def test_oldest_last_indexed(self, tmp_path: Path) -> None:
        """oldest_last_indexed is the earliest last_indexed_at across all sources."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_collection_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        assert result["oldest_last_indexed"] == "2024-01-01T08:00:00"

    def test_newest_last_indexed(self, tmp_path: Path) -> None:
        """newest_last_indexed is the most recent last_indexed_at across all sources."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        _seed_db(tmp_path, config)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_collection_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        assert result["newest_last_indexed"] == "2024-02-15T12:00:00"

    def test_timestamps_none_when_no_sources(self, tmp_path: Path) -> None:
        """oldest/newest timestamps are None when no sources have been indexed."""
        from ragling.mcp_server import create_server
        from ragling.db import get_connection, init_db

        config = _make_config(tmp_path)
        # Seed only collections with no sources
        conn = get_connection(config)
        init_db(conn, config)
        conn.execute(
            "INSERT OR IGNORE INTO collections (name, collection_type) VALUES (?, ?)",
            ("empty", "project"),
        )
        conn.commit()
        conn.close()

        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_collection_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        assert result["oldest_last_indexed"] is None
        assert result["newest_last_indexed"] is None

    def test_empty_database(self, tmp_path: Path) -> None:
        """All counts are zero and timestamps are None when the DB is empty."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        server = create_server(group_name="default", config=config)
        fn = server._tool_manager._tools["rag_collection_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        assert result["total_collections"] == 0
        assert result["total_sources"] == 0
        assert result["total_chunks"] == 0
        assert result["collections_by_type"] == {}
        assert result["oldest_last_indexed"] is None
        assert result["newest_last_indexed"] is None


class TestCollectionStatsVisibility:
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
        fn = tools["rag_collection_stats"].fn

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

    def test_authenticated_user_type_breakdown_filtered(self, tmp_path: Path) -> None:
        """collections_by_type only counts visible collections."""
        _server, tools = self._setup_server(tmp_path, user_collections=["obsidian"])
        fn = tools["rag_collection_stats"].fn

        mock_token = MagicMock()
        mock_token.client_id = "alice"
        with patch("ragling.tools.helpers.get_access_token", return_value=mock_token):
            result = fn()

        by_type = result["collections_by_type"]
        # Only obsidian (system) is visible — email is excluded
        assert by_type.get("system", 0) == 1
        assert by_type.get("project", 0) == 0

    def test_unauthenticated_sees_all_collections(self, tmp_path: Path) -> None:
        """Without auth, all collections are included in stats."""
        _server, tools = self._setup_server(tmp_path, user_collections=["obsidian"])
        fn = tools["rag_collection_stats"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        assert result["total_collections"] == 3
        assert result["total_sources"] == 3
        assert result["total_chunks"] == 8

    def test_timestamps_scoped_to_visible_collections(self, tmp_path: Path) -> None:
        """Timestamps reflect only the sources in visible collections."""
        _server, tools = self._setup_server(tmp_path, user_collections=["obsidian"])
        fn = tools["rag_collection_stats"].fn

        mock_token = MagicMock()
        mock_token.client_id = "alice"
        with patch("ragling.tools.helpers.get_access_token", return_value=mock_token):
            result = fn()

        # Only obsidian sources visible: 2024-01-01 and 2024-01-02
        assert result["oldest_last_indexed"] == "2024-01-01T08:00:00"
        assert result["newest_last_indexed"] == "2024-01-02T10:00:00"


class TestCollectionStatsRegistration:
    """Verify the tool is properly registered via register_all_tools."""

    def test_tool_is_registered_in_server(self, tmp_path: Path) -> None:
        """rag_collection_stats appears in the server tool manager."""
        from ragling.mcp_server import create_server

        config = _make_config(tmp_path)
        server = create_server(group_name="default", config=config)
        assert "rag_collection_stats" in server._tool_manager._tools

    def test_register_function_exists(self) -> None:
        """collection_stats module exposes a register() callable."""
        from ragling.tools import collection_stats

        assert callable(collection_stats.register)
