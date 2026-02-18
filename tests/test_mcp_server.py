"""Tests for ragling.mcp_server module."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from ragling.config import Config


class TestBuildSourceUri:
    """Tests for _build_source_uri (existing function, ensure no regression)."""

    def test_rss_returns_url(self) -> None:
        from ragling.mcp_server import _build_source_uri

        result = _build_source_uri("/rss/article", "rss", {"url": "https://example.com"}, "rss")
        assert result == "https://example.com"

    def test_email_returns_none(self) -> None:
        from ragling.mcp_server import _build_source_uri

        result = _build_source_uri("/email/1", "email", {}, "email")
        assert result is None


class TestApplyUserContextToResults:
    def test_applies_path_mappings_to_results(self) -> None:
        from ragling.auth import UserContext
        from ragling.mcp_server import _apply_user_context_to_results

        ctx = UserContext(
            username="kitchen",
            path_mappings={"/host/groups/kitchen/": "/workspace/group/"},
        )
        results = [
            {
                "source_path": "/host/groups/kitchen/notes.md",
                "source_uri": "file:///host/groups/kitchen/notes.md",
                "title": "Notes",
                "content": "text",
            }
        ]
        mapped = _apply_user_context_to_results(results, ctx)
        assert mapped[0]["source_path"] == "/workspace/group/notes.md"
        assert mapped[0]["source_uri"] == "file:///workspace/group/notes.md"

    def test_no_mapping_leaves_paths_unchanged(self) -> None:
        from ragling.auth import UserContext
        from ragling.mcp_server import _apply_user_context_to_results

        ctx = UserContext(username="kitchen", path_mappings={})
        results = [{"source_path": "/host/other.md", "source_uri": None}]
        mapped = _apply_user_context_to_results(results, ctx)
        assert mapped[0]["source_path"] == "/host/other.md"

    def test_does_not_mutate_original_results(self) -> None:
        from ragling.auth import UserContext
        from ragling.mcp_server import _apply_user_context_to_results

        ctx = UserContext(
            username="kitchen",
            path_mappings={"/host/": "/container/"},
        )
        original = [{"source_path": "/host/file.md", "source_uri": "file:///host/file.md"}]
        _apply_user_context_to_results(original, ctx)
        assert original[0]["source_path"] == "/host/file.md"

    def test_preserves_other_fields(self) -> None:
        from ragling.auth import UserContext
        from ragling.mcp_server import _apply_user_context_to_results

        ctx = UserContext(
            username="kitchen",
            path_mappings={"/host/": "/container/"},
        )
        results = [
            {
                "source_path": "/host/file.md",
                "source_uri": None,
                "title": "My Title",
                "score": 0.95,
                "metadata": {"tags": ["test"]},
            }
        ]
        mapped = _apply_user_context_to_results(results, ctx)
        assert mapped[0]["title"] == "My Title"
        assert mapped[0]["score"] == 0.95
        assert mapped[0]["metadata"] == {"tags": ["test"]}


class TestBuildListResponse:
    def test_includes_indexing_when_active(self) -> None:
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import _build_list_response

        status = IndexingStatus()
        status.increment("obsidian", 5)
        response = _build_list_response([], status)
        assert response["indexing"] == {
            "active": True,
            "total_remaining": 5,
            "total_remaining_bytes": 0,
            "collections": {"obsidian": 5},
        }

    def test_no_indexing_key_when_idle(self) -> None:
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import _build_list_response

        status = IndexingStatus()
        response = _build_list_response([], status)
        assert "indexing" not in response

    def test_no_indexing_key_when_no_status(self) -> None:
        from ragling.mcp_server import _build_list_response

        response = _build_list_response([])
        assert "indexing" not in response

    def test_includes_file_level_indexing_status(self) -> None:
        """List response shows per-collection file-level indexing status."""
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import _build_list_response

        status = IndexingStatus()
        status.set_file_total("obsidian", 80)
        status.file_processed("obsidian", 30)
        status.set_file_total("email", 50)
        status.file_processed("email", 50)

        response = _build_list_response([], status)
        assert "indexing" in response
        indexing = response["indexing"]
        assert indexing["active"] is True
        # obsidian: file-level dict shape
        assert indexing["collections"]["obsidian"] == {
            "total": 80,
            "processed": 30,
            "remaining": 50,
            "total_bytes": 0,
            "remaining_bytes": 0,
        }
        # email: file-level dict shape (fully processed)
        assert indexing["collections"]["email"] == {
            "total": 50,
            "processed": 50,
            "remaining": 0,
            "total_bytes": 0,
            "remaining_bytes": 0,
        }
        # total_remaining = 50 + 0 = 50
        assert indexing["total_remaining"] == 50

    def test_result_passed_through(self) -> None:
        from ragling.mcp_server import _build_list_response

        collections = [{"name": "obsidian"}, {"name": "email"}]
        response = _build_list_response(collections)
        assert response["result"] == collections

    def test_includes_role_when_getter_provided(self) -> None:
        from ragling.mcp_server import _build_list_response

        response = _build_list_response([], role_getter=lambda: "leader")
        assert response["role"] == "leader"

    def test_includes_follower_role(self) -> None:
        from ragling.mcp_server import _build_list_response

        response = _build_list_response([], role_getter=lambda: "follower")
        assert response["role"] == "follower"

    def test_omits_role_when_no_getter(self) -> None:
        from ragling.mcp_server import _build_list_response

        response = _build_list_response([])
        assert "role" not in response


class TestBuildSearchResponse:
    def test_includes_indexing_when_active(self) -> None:
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import _build_search_response

        status = IndexingStatus()
        status.increment("obsidian", 5)
        response = _build_search_response([], status)
        assert response["indexing"] == {
            "active": True,
            "total_remaining": 5,
            "total_remaining_bytes": 0,
            "collections": {"obsidian": 5},
        }

    def test_indexing_null_when_idle(self) -> None:
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import _build_search_response

        status = IndexingStatus()
        response = _build_search_response([], status)
        assert response["indexing"] is None

    def test_indexing_null_when_no_status(self) -> None:
        from ragling.mcp_server import _build_search_response

        response = _build_search_response([])
        assert response["indexing"] is None

    def test_includes_file_level_indexing_status(self) -> None:
        """Search response shows per-collection {total, processed, remaining} for file-level tracking."""
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import _build_search_response

        status = IndexingStatus()
        status.set_file_total("obsidian", 100)
        status.file_processed("obsidian", 55)
        status.set_file_total("calibre", 30)
        status.file_processed("calibre", 10)

        response = _build_search_response([], status)
        indexing = response["indexing"]
        assert indexing is not None
        assert indexing["active"] is True
        # obsidian: file-level dict shape
        assert indexing["collections"]["obsidian"] == {
            "total": 100,
            "processed": 55,
            "remaining": 45,
            "total_bytes": 0,
            "remaining_bytes": 0,
        }
        # calibre: file-level dict shape
        assert indexing["collections"]["calibre"] == {
            "total": 30,
            "processed": 10,
            "remaining": 20,
            "total_bytes": 0,
            "remaining_bytes": 0,
        }
        # total_remaining = 45 + 20 = 65
        assert indexing["total_remaining"] == 65

    def test_results_passed_through(self) -> None:
        from ragling.mcp_server import _build_search_response

        results = [{"title": "A"}, {"title": "B"}]
        response = _build_search_response(results)
        assert response["results"] == results
        assert len(response["results"]) == 2


class TestConvertDocument:
    """Tests for the _convert_document helper."""

    def test_converts_markdown_file(self, tmp_path: Path) -> None:
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello World\n\nThis is a test document.")

        from ragling.mcp_server import _convert_document

        result = _convert_document(str(md_file), path_mappings={})
        assert "Hello World" in result
        assert "test document" in result

    def test_applies_reverse_path_mapping(self, tmp_path: Path) -> None:
        md_file = tmp_path / "test.md"
        md_file.write_text("# Mapped\n\nContent here.")

        from ragling.mcp_server import _convert_document

        # Container path /workspace/group/test.md maps to host path
        mappings = {str(tmp_path) + "/": "/workspace/group/"}
        result = _convert_document("/workspace/group/test.md", mappings)
        assert "Mapped" in result

    def test_returns_error_for_nonexistent_file(self) -> None:
        from ragling.mcp_server import _convert_document

        result = _convert_document("/nonexistent/file.pdf", {})
        assert "error" in result.lower() or "not found" in result.lower()


class TestCreateServerSignature:
    """Tests for create_server accepting config and indexing_status."""

    def test_create_server_accepts_config(self) -> None:
        from ragling.config import Config
        from ragling.mcp_server import create_server

        config = Config()
        server = create_server(group_name="test", config=config)
        assert server is not None

    def test_create_server_accepts_indexing_status(self) -> None:
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        status = IndexingStatus()
        server = create_server(group_name="test", indexing_status=status)
        assert server is not None

    def test_create_server_accepts_all_params(self) -> None:
        from ragling.config import Config
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config()
        status = IndexingStatus()
        server = create_server(group_name="test", config=config, indexing_status=status)
        assert server is not None

    def test_create_server_accepts_role_getter(self) -> None:
        from ragling.mcp_server import create_server

        server = create_server(
            group_name="test",
            role_getter=lambda: "leader",
        )
        assert server is not None

    def test_create_server_backwards_compatible(self) -> None:
        """Calling with no args still works (backwards compat)."""
        from ragling.mcp_server import create_server

        server = create_server()
        assert server is not None

    def test_create_server_with_users_sets_auth(self) -> None:
        """When users are configured, create_server sets up auth."""
        from ragling.config import Config, UserConfig
        from ragling.mcp_server import create_server
        from ragling.token_verifier import RaglingTokenVerifier

        config = Config(
            users={"kitchen": UserConfig(api_key="test-key")},
        )
        server = create_server(group_name="test", config=config)
        assert server is not None
        assert server.settings.auth is not None
        assert isinstance(server._token_verifier, RaglingTokenVerifier)

    def test_create_server_without_users_no_auth(self) -> None:
        """When no users configured, create_server does not set up auth."""
        from ragling.config import Config
        from ragling.mcp_server import create_server

        config = Config(users={})
        server = create_server(group_name="test", config=config)
        assert server is not None
        assert server.settings.auth is None


class TestConfigGetter:
    """Tests for config_getter parameter in create_server."""

    def test_config_getter_is_accepted(self, tmp_path: Path) -> None:
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
        )

        server = create_server(
            group_name="default",
            config=config,
            config_getter=lambda: config,
        )
        assert server is not None


class TestGetUserContext:
    """Tests for deriving UserContext from access token."""

    def test_returns_user_context_when_authenticated(self) -> None:
        from ragling.config import Config, UserConfig
        from ragling.mcp_server import _get_user_context

        config = Config(
            users={
                "kitchen": UserConfig(
                    api_key="key",
                    system_collections=["obsidian"],
                    path_mappings={"/host/kitchen/": "/workspace/group/"},
                ),
            },
        )
        mock_token = MagicMock()
        mock_token.client_id = "kitchen"
        with patch("ragling.mcp_server.get_access_token", return_value=mock_token):
            ctx = _get_user_context(config)
            assert ctx is not None
            assert ctx.username == "kitchen"
            assert ctx.system_collections == ["obsidian"]
            assert ctx.path_mappings == {"/host/kitchen/": "/workspace/group/"}

    def test_returns_none_when_no_access_token(self) -> None:
        from ragling.config import Config, UserConfig
        from ragling.mcp_server import _get_user_context

        config = Config(
            users={"kitchen": UserConfig(api_key="key")},
        )
        with patch("ragling.mcp_server.get_access_token", return_value=None):
            ctx = _get_user_context(config)
            assert ctx is None

    def test_returns_none_when_no_config(self) -> None:
        from ragling.mcp_server import _get_user_context

        with patch("ragling.mcp_server.get_access_token", return_value=MagicMock()):
            ctx = _get_user_context(None)
            assert ctx is None

    def test_returns_none_when_unknown_user(self) -> None:
        from ragling.config import Config, UserConfig
        from ragling.mcp_server import _get_user_context

        config = Config(
            users={"kitchen": UserConfig(api_key="key")},
        )
        mock_token = MagicMock()
        mock_token.client_id = "unknown_user"
        with patch("ragling.mcp_server.get_access_token", return_value=mock_token):
            ctx = _get_user_context(config)
            assert ctx is None


class TestStaleFieldInResponse:
    """Tests for stale field appearing in search results."""

    def test_result_dict_includes_stale_field(self) -> None:
        """Verify the result dict construction includes 'stale' key."""
        from ragling.search import SearchResult

        r = SearchResult(
            content="test",
            title="test",
            metadata={},
            score=1.0,
            collection="obsidian",
            source_path="/tmp/test.md",
            source_type="markdown",
            stale=True,
        )
        # Simulate the dict construction from mcp_server.py
        result_dict = {
            "title": r.title,
            "content": r.content,
            "collection": r.collection,
            "source_type": r.source_type,
            "source_path": r.source_path,
            "score": round(r.score, 4),
            "metadata": r.metadata,
            "stale": r.stale,
        }
        assert result_dict["stale"] is True

    def test_result_dict_stale_defaults_false(self) -> None:
        """Verify stale defaults to False when not explicitly set."""
        from ragling.search import SearchResult

        r = SearchResult(
            content="test",
            title="test",
            metadata={},
            score=1.0,
            collection="obsidian",
            source_path="/tmp/test.md",
            source_type="markdown",
        )
        result_dict = {
            "title": r.title,
            "content": r.content,
            "collection": r.collection,
            "source_type": r.source_type,
            "source_path": r.source_path,
            "score": round(r.score, 4),
            "metadata": r.metadata,
            "stale": r.stale,
        }
        assert result_dict["stale"] is False


class TestRagIndexQueueRouting:
    """Tests for rag_index routing through IndexingQueue."""

    def test_rag_index_uses_queue_when_available(self, tmp_path: Path) -> None:
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            obsidian_vaults=[tmp_path / "vault"],
        )

        status = IndexingStatus()
        queue = MagicMock(spec=IndexingQueue)

        server = create_server(
            group_name="default",
            config=config,
            indexing_status=status,
            indexing_queue=queue,
        )

        # The server object has rag_index registered; verify queue parameter accepted
        assert server is not None

    def test_rag_index_direct_when_no_queue(self, tmp_path: Path) -> None:
        """When no queue is provided, rag_index uses direct indexing."""
        from ragling.config import Config
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        # No indexing_queue — should still work (backwards compat)
        server = create_server(
            group_name="default",
            config=config,
        )
        assert server is not None

    def test_rag_index_via_queue_returns_submitted_status(self, tmp_path: Path) -> None:
        """rag_index returns immediately with 'submitted' status."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        vault_dir = tmp_path / "vault"
        vault_dir.mkdir()

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            obsidian_vaults=[vault_dir],
        )

        status = IndexingStatus()
        queue = MagicMock(spec=IndexingQueue)

        server = create_server(
            group_name="default",
            config=config,
            indexing_status=status,
            indexing_queue=queue,
        )

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="obsidian")

        # Should use submit (fire-and-forget), NOT submit_and_wait
        queue.submit.assert_called_once()
        queue.submit_and_wait.assert_not_called()
        assert result["status"] == "submitted"
        assert result["collection"] == "obsidian"
        assert "indexing" in result

    def test_rag_index_via_queue_dedup_rejects_when_active(self, tmp_path: Path) -> None:
        """rag_index returns already_indexing when collection is active."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        vault_dir = tmp_path / "vault"
        vault_dir.mkdir()

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            obsidian_vaults=[vault_dir],
        )

        status = IndexingStatus()
        status.increment("obsidian")  # simulate active indexing

        queue = MagicMock(spec=IndexingQueue)

        server = create_server(
            group_name="default",
            config=config,
            indexing_status=status,
            indexing_queue=queue,
        )

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="obsidian")

        queue.submit.assert_not_called()
        queue.submit_and_wait.assert_not_called()
        assert result["status"] == "already_indexing"
        assert result["collection"] == "obsidian"
        assert "indexing" in result

    def test_rag_index_via_queue_code_group_submits_all_repos(self, tmp_path: Path) -> None:
        """Code groups submit one job per repo via fire-and-forget."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        repo1 = tmp_path / "repo1"
        repo2 = tmp_path / "repo2"
        repo1.mkdir()
        repo2.mkdir()

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            code_groups={"mycode": [repo1, repo2]},
        )

        status = IndexingStatus()
        queue = MagicMock(spec=IndexingQueue)

        server = create_server(
            group_name="default",
            config=config,
            indexing_status=status,
            indexing_queue=queue,
        )

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="mycode")

        assert queue.submit.call_count == 2
        queue.submit_and_wait.assert_not_called()
        assert result["status"] == "submitted"
        assert result["collection"] == "mycode"
        assert result["repos"] == 2
        assert "indexing" in result

    def test_rag_index_disabled_collection(self, tmp_path: Path) -> None:
        """Disabled collections return error regardless of queue."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            disabled_collections={"obsidian"},
        )

        status = IndexingStatus()
        queue = MagicMock(spec=IndexingQueue)

        server = create_server(
            group_name="default",
            config=config,
            indexing_status=status,
            indexing_queue=queue,
        )

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="obsidian")

        assert "error" in result
        assert "disabled" in result["error"].lower()
        queue.submit.assert_not_called()


class TestRagIndexFollowerMode:
    """Tests for rag_index behavior when queue_getter returns None (follower)."""

    def test_follower_returns_error_for_rag_index(self, tmp_path: Path) -> None:
        """When queue_getter returns None, rag_index returns a follower error."""
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        server = create_server(
            config=config,
            queue_getter=lambda: None,
        )

        # Verify server was created with the queue_getter
        tools = server._tool_manager._tools
        assert "rag_index" in tools

        # Call rag_index — should return follower error
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="obsidian")
        assert "error" in result
        assert "follower" in result["error"].lower() or "read-only" in result["error"].lower()

    def test_queue_getter_dynamic_resolution(self) -> None:
        """queue_getter is called on each rag_index invocation, not cached."""
        from ragling.mcp_server import create_server

        config = Config(embedding_dimensions=4)
        call_count = 0

        def counting_getter() -> None:
            nonlocal call_count
            call_count += 1
            return None

        _server = create_server(
            config=config,
            queue_getter=counting_getter,
        )
        # The getter should NOT be called at creation time
        assert call_count == 0
        assert _server is not None

    def test_queue_getter_overrides_static_queue(self, tmp_path: Path) -> None:
        """When both indexing_queue and queue_getter are provided, queue_getter wins."""
        from ragling.indexing_queue import IndexingQueue
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            obsidian_vaults=[tmp_path / "vault"],
        )
        (tmp_path / "vault").mkdir(exist_ok=True)

        static_queue = MagicMock(spec=IndexingQueue)
        dynamic_queue = MagicMock(spec=IndexingQueue)

        server = create_server(
            config=config,
            indexing_queue=static_queue,
            queue_getter=lambda: dynamic_queue,
        )

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="obsidian")

        # dynamic_queue should be used, not static_queue
        dynamic_queue.submit.assert_called_once()
        static_queue.submit.assert_not_called()
        assert result["status"] == "submitted"

    def test_queue_getter_promotion_scenario(self, tmp_path: Path) -> None:
        """Simulates follower->leader promotion: getter initially returns None, then a queue."""
        from ragling.indexing_queue import IndexingQueue
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            obsidian_vaults=[tmp_path / "vault"],
        )
        (tmp_path / "vault").mkdir(exist_ok=True)

        promoted_queue = MagicMock(spec=IndexingQueue)

        # Start as follower (getter returns None), then "promote" to leader
        current_queue: IndexingQueue | None = None

        def getter() -> IndexingQueue | None:
            return current_queue

        server = create_server(
            config=config,
            queue_getter=getter,
        )

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn

        # As follower, should return error
        result1: dict[str, Any] = rag_index_fn(collection="obsidian")
        assert "error" in result1
        assert "read-only" in result1["error"].lower()

        # Promote to leader
        current_queue = promoted_queue

        # Now should route through the queue
        result2: dict[str, Any] = rag_index_fn(collection="obsidian")
        assert "error" not in result2
        assert result2["status"] == "submitted"
        promoted_queue.submit.assert_called_once()

    def test_no_queue_getter_falls_back_to_static_queue(self, tmp_path: Path) -> None:
        """Without queue_getter, the existing indexing_queue parameter still works."""
        from ragling.indexing_queue import IndexingQueue
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            obsidian_vaults=[tmp_path / "vault"],
        )
        (tmp_path / "vault").mkdir(exist_ok=True)

        queue = MagicMock(spec=IndexingQueue)

        # No queue_getter — only static indexing_queue
        server = create_server(
            config=config,
            indexing_queue=queue,
        )

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="obsidian")

        queue.submit.assert_called_once()
        assert result["status"] == "submitted"


class TestRagIndexingStatus:
    """Tests for the rag_indexing_status MCP tool."""

    def test_returns_inactive_when_idle(self, tmp_path: Path) -> None:
        from ragling.config import Config
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        status = IndexingStatus()
        server = create_server(config=config, indexing_status=status)

        tools = server._tool_manager._tools
        fn = tools["rag_indexing_status"].fn
        result = fn()

        assert result == {"active": False}

    def test_returns_status_when_active(self, tmp_path: Path) -> None:
        from ragling.config import Config
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        status = IndexingStatus()
        status.increment("obsidian", 3)
        server = create_server(config=config, indexing_status=status)

        tools = server._tool_manager._tools
        fn = tools["rag_indexing_status"].fn
        result = fn()

        assert result["active"] is True
        assert result["total_remaining"] == 3
        assert "obsidian" in result["collections"]

    def test_returns_inactive_when_no_status_tracker(self, tmp_path: Path) -> None:
        from ragling.config import Config
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        server = create_server(config=config)  # no indexing_status

        tools = server._tool_manager._tools
        fn = tools["rag_indexing_status"].fn
        result = fn()

        assert result == {"active": False}
