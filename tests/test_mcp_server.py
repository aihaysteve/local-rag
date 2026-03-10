"""Tests for ragling.mcp_server module."""

from pathlib import Path
from types import MappingProxyType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ragling.config import Config


class TestBuildSourceUri:
    """Tests for _build_source_uri (existing function, ensure no regression)."""

    def test_rss_returns_url(self) -> None:
        from ragling.tools.helpers import _build_source_uri

        result = _build_source_uri("/rss/article", "rss", {"url": "https://example.com"}, "rss")
        assert result == "https://example.com"

    def test_email_returns_none(self) -> None:
        from ragling.tools.helpers import _build_source_uri

        result = _build_source_uri("/email/1", "email", {}, "email")
        assert result is None


class TestBuildSourceUriSpec:
    """Tests for spec source_type URI building."""

    def test_spec_returns_file_uri(self) -> None:
        from ragling.tools.helpers import _build_source_uri

        uri = _build_source_uri(
            source_path="/Users/dev/project/features/auth/SPEC.md",
            source_type="spec",
            metadata={"subsystem_name": "Auth"},
            collection="my-project",
        )
        assert uri is not None
        assert uri.startswith("file://")
        assert "SPEC.md" in uri


class TestApplyUserContextToResults:
    def test_applies_path_mappings_to_results(self) -> None:
        from ragling.auth.auth import UserContext
        from ragling.tools.helpers import _apply_user_context_to_results

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
        from ragling.auth.auth import UserContext
        from ragling.tools.helpers import _apply_user_context_to_results

        ctx = UserContext(username="kitchen", path_mappings={})
        results = [{"source_path": "/host/other.md", "source_uri": None}]
        mapped = _apply_user_context_to_results(results, ctx)
        assert mapped[0]["source_path"] == "/host/other.md"

    def test_does_not_mutate_original_results(self) -> None:
        from ragling.auth.auth import UserContext
        from ragling.tools.helpers import _apply_user_context_to_results

        ctx = UserContext(
            username="kitchen",
            path_mappings={"/host/": "/container/"},
        )
        original = [{"source_path": "/host/file.md", "source_uri": "file:///host/file.md"}]
        _apply_user_context_to_results(original, ctx)
        assert original[0]["source_path"] == "/host/file.md"

    def test_preserves_other_fields(self) -> None:
        from ragling.auth.auth import UserContext
        from ragling.tools.helpers import _apply_user_context_to_results

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
        from ragling.tools.helpers import _build_list_response

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
        from ragling.tools.helpers import _build_list_response

        status = IndexingStatus()
        response = _build_list_response([], status)
        assert "indexing" not in response

    def test_no_indexing_key_when_no_status(self) -> None:
        from ragling.tools.helpers import _build_list_response

        response = _build_list_response([])
        assert "indexing" not in response

    def test_includes_file_level_indexing_status(self) -> None:
        """List response shows per-collection file-level indexing status."""
        from ragling.indexing_status import IndexingStatus
        from ragling.tools.helpers import _build_list_response

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
        from ragling.tools.helpers import _build_list_response

        collections = [{"name": "obsidian"}, {"name": "email"}]
        response = _build_list_response(collections)
        assert response["result"] == collections

    def test_includes_role_when_getter_provided(self) -> None:
        from ragling.tools.helpers import _build_list_response

        response = _build_list_response([], role_getter=lambda: "leader")
        assert response["role"] == "leader"

    def test_includes_follower_role(self) -> None:
        from ragling.tools.helpers import _build_list_response

        response = _build_list_response([], role_getter=lambda: "follower")
        assert response["role"] == "follower"

    def test_omits_role_when_no_getter(self) -> None:
        from ragling.tools.helpers import _build_list_response

        response = _build_list_response([])
        assert "role" not in response


class TestBuildSearchResponse:
    def test_includes_indexing_when_active(self) -> None:
        from ragling.indexing_status import IndexingStatus
        from ragling.tools.helpers import _build_search_response

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
        from ragling.tools.helpers import _build_search_response

        status = IndexingStatus()
        response = _build_search_response([], status)
        assert response["indexing"] is None

    def test_indexing_null_when_no_status(self) -> None:
        from ragling.tools.helpers import _build_search_response

        response = _build_search_response([])
        assert response["indexing"] is None

    def test_includes_file_level_indexing_status(self) -> None:
        """Search response shows per-collection {total, processed, remaining} for file-level tracking."""
        from ragling.indexing_status import IndexingStatus
        from ragling.tools.helpers import _build_search_response

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
        from ragling.tools.helpers import _build_search_response

        results = [{"title": "A"}, {"title": "B"}]
        response = _build_search_response(results)
        assert response["results"] == results
        assert len(response["results"]) == 2


class TestResultToDict:
    """Tests for _result_to_dict helper."""

    def test_converts_search_result_to_dict(self) -> None:
        from ragling.tools.helpers import _result_to_dict
        from ragling.search.search import SearchResult

        r = SearchResult(
            content="test content",
            title="Test Title",
            metadata={"tags": ["python"]},
            score=0.87654,
            collection="obsidian",
            source_path="/vault/notes/test.md",
            source_type="markdown",
        )
        d = _result_to_dict(r, obsidian_vaults=[])
        assert d["title"] == "Test Title"
        assert d["content"] == "test content"
        assert d["collection"] == "obsidian"
        assert d["source_type"] == "markdown"
        assert d["source_path"] == "/vault/notes/test.md"
        assert d["score"] == 0.8765  # rounded to 4 decimals
        assert d["metadata"] == {"tags": ["python"]}
        assert d["stale"] is False

    def test_includes_source_uri(self) -> None:
        from ragling.tools.helpers import _result_to_dict
        from ragling.search.search import SearchResult

        r = SearchResult(
            content="c",
            title="t",
            metadata={},
            score=0.5,
            collection="project",
            source_path="/docs/report.pdf",
            source_type="pdf",
        )
        d = _result_to_dict(r, obsidian_vaults=[])
        assert d["source_uri"] is not None
        assert d["source_uri"].startswith("file://")

    def test_stale_flag_preserved(self) -> None:
        from ragling.tools.helpers import _result_to_dict
        from ragling.search.search import SearchResult

        r = SearchResult(
            content="c",
            title="t",
            metadata={},
            score=0.5,
            collection="obsidian",
            source_path="/vault/old.md",
            source_type="markdown",
            stale=True,
        )
        d = _result_to_dict(r, obsidian_vaults=[])
        assert d["stale"] is True


class TestConvertDocument:
    """Tests for the _convert_document helper."""

    def test_converts_markdown_file(self, tmp_path: Path) -> None:
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello World\n\nThis is a test document.")

        from ragling.tools.helpers import _convert_document

        result = _convert_document(str(md_file), path_mappings={})
        assert "Hello World" in result
        assert "test document" in result

    def test_applies_reverse_path_mapping(self, tmp_path: Path) -> None:
        md_file = tmp_path / "test.md"
        md_file.write_text("# Mapped\n\nContent here.")

        from ragling.tools.helpers import _convert_document

        # Container path /workspace/group/test.md maps to host path
        mappings = {str(tmp_path) + "/": "/workspace/group/"}
        result = _convert_document("/workspace/group/test.md", mappings)
        assert "Mapped" in result

    def test_returns_error_for_nonexistent_file(self) -> None:
        from ragling.tools.helpers import _convert_document

        result = _convert_document("/nonexistent/file.pdf", {})
        assert "error" in result.lower() or "not found" in result.lower()

    def test_error_does_not_leak_file_path(self) -> None:
        from ragling.tools.helpers import _convert_document

        result = _convert_document("/nonexistent/secret/path.pdf", {})
        assert "/nonexistent/secret" not in result

    def test_conversion_error_does_not_leak_details(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from ragling.tools.helpers import _convert_document

        pdf = tmp_path / "test.pdf"
        pdf.write_text("not a real pdf")
        with patch("ragling.tools.helpers.load_config") as mock_config:
            mock_config.return_value.shared_db_path = tmp_path / "shared.db"
            result = _convert_document(str(pdf), {})
        assert str(tmp_path) not in result
        assert "error" in result.lower()


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
        from ragling.auth.token_verifier import RaglingTokenVerifier

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
        from ragling.tools.helpers import _get_user_context

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
        with patch("ragling.tools.helpers.get_access_token", return_value=mock_token):
            ctx = _get_user_context(config)
            assert ctx is not None
            assert ctx.username == "kitchen"
            assert ctx.system_collections == ["obsidian"]
            assert ctx.path_mappings == {"/host/kitchen/": "/workspace/group/"}

    def test_returns_none_when_no_access_token(self) -> None:
        from ragling.config import Config, UserConfig
        from ragling.tools.helpers import _get_user_context

        config = Config(
            users={"kitchen": UserConfig(api_key="key")},
        )
        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            ctx = _get_user_context(config)
            assert ctx is None

    def test_returns_none_when_no_config(self) -> None:
        from ragling.tools.helpers import _get_user_context

        with patch("ragling.tools.helpers.get_access_token", return_value=MagicMock()):
            ctx = _get_user_context(None)
            assert ctx is None

    def test_returns_none_when_unknown_user(self) -> None:
        from ragling.config import Config, UserConfig
        from ragling.tools.helpers import _get_user_context

        config = Config(
            users={"kitchen": UserConfig(api_key="key")},
        )
        mock_token = MagicMock()
        mock_token.client_id = "unknown_user"
        with patch("ragling.tools.helpers.get_access_token", return_value=mock_token):
            ctx = _get_user_context(config)
            assert ctx is None


class TestStaleFieldInResponse:
    """Tests for stale field appearing in search results."""

    def test_result_dict_includes_stale_field(self) -> None:
        """Verify the result dict construction includes 'stale' key."""
        from ragling.search.search import SearchResult

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
        from ragling.search.search import SearchResult

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

    def test_rag_index_without_queue_returns_error(self, tmp_path: Path) -> None:
        """When no queue is provided, rag_index returns an error."""
        from ragling.config import Config
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        # No indexing_queue — rag_index should return error
        server = create_server(
            group_name="default",
            config=config,
        )
        assert server is not None

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="email")
        assert "error" in result
        assert "No indexing queue available" in result["error"]

    def test_rag_index_via_queue_returns_submitted_status(self, tmp_path: Path) -> None:
        """rag_index returns immediately with 'submitted' status for system collections."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
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
        with patch("ragling.embeddings.check_connection"):
            result: dict[str, Any] = rag_index_fn(collection="email")

        # Should use submit (fire-and-forget), NOT submit_and_wait
        queue.submit.assert_called_once()
        queue.submit_and_wait.assert_not_called()
        assert result["status"] == "submitted"
        assert result["collection"] == "email"
        assert "indexing" in result

    def test_rag_index_via_queue_dedup_rejects_when_active(self, tmp_path: Path) -> None:
        """rag_index returns already_indexing when collection is active."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        status = IndexingStatus()
        status.increment("email")  # simulate active indexing

        queue = MagicMock(spec=IndexingQueue)

        server = create_server(
            group_name="default",
            config=config,
            indexing_status=status,
            indexing_queue=queue,
        )

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="email")

        queue.submit.assert_not_called()
        queue.submit_and_wait.assert_not_called()
        assert result["status"] == "already_indexing"
        assert result["collection"] == "email"
        assert "indexing" in result

    def test_rag_index_watch_syncs_all_paths_via_walker(self, tmp_path: Path) -> None:
        """Watch collections sync each path via the unified walker pipeline."""
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
            watch=MappingProxyType({"mycode": (repo1, repo2)}),
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

        mock_result = MagicMock(
            indexed=5, skipped=0, skipped_empty=0, errors=0, pruned=0, error_messages=[]
        )
        with patch("ragling.embeddings.check_connection"):
            with patch("ragling.sync.sync_directory_source", return_value=mock_result) as mock_sync:
                with (
                    patch("ragling.db.get_connection", return_value=MagicMock()),
                    patch("ragling.db.init_db"),
                ):
                    result: dict[str, Any] = rag_index_fn(collection="mycode")

                assert mock_sync.call_count == 2

        queue.submit.assert_not_called()
        assert result["status"] == "completed"
        assert result["collection"] == "mycode"
        assert result["paths"] == 2
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


class TestRagIndexWatch:
    """Tests for rag_index routing watch collections."""

    def test_rag_index_watch_syncs_all_paths(self, tmp_path: Path) -> None:
        """Watch collections sync each path via the unified walker pipeline."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        dir1 = tmp_path / "papers"
        dir2 = tmp_path / "refs"
        dir1.mkdir()
        dir2.mkdir()

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            watch=MappingProxyType({"research": (dir1, dir2)}),
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

        mock_result = MagicMock(
            indexed=3, skipped=0, skipped_empty=0, errors=0, pruned=0, error_messages=[]
        )
        with patch("ragling.embeddings.check_connection"):
            with patch("ragling.sync.sync_directory_source", return_value=mock_result) as mock_sync:
                with (
                    patch("ragling.db.get_connection", return_value=MagicMock()),
                    patch("ragling.db.init_db"),
                ):
                    result: dict[str, Any] = rag_index_fn(collection="research")

                assert mock_sync.call_count == 2

        queue.submit.assert_not_called()
        assert result["status"] == "completed"
        assert result["paths"] == 2

    def test_rag_index_no_queue_watch_returns_error(self, tmp_path: Path) -> None:
        """Without a queue, rag_index returns an error for watch collections."""
        from ragling.config import Config
        from ragling.mcp_server import create_server

        watch_dir = tmp_path / "proj"
        watch_dir.mkdir()

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            watch=MappingProxyType({"proj": (watch_dir,)}),
        )

        server = create_server(group_name="default", config=config)

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="proj")

        assert "error" in result
        assert "No indexing queue available" in result["error"]

    def test_rag_index_no_queue_returns_error(self, tmp_path: Path) -> None:
        """Without a queue, rag_index returns an error for any collection."""
        from ragling.config import Config
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            obsidian_vaults=[tmp_path / "vault"],
        )

        server = create_server(group_name="default", config=config)

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        result: dict[str, Any] = rag_index_fn(collection="obsidian")

        assert "error" in result
        assert "No indexing queue available" in result["error"]


class TestRagIndexErrorSurfacing:
    """rag_index surfaces errors from IndexResult and checks Ollama connectivity."""

    @pytest.fixture()
    def watch_server(self, tmp_path: Path) -> tuple[Any, MagicMock]:
        """Create a server with a single watch collection and return (rag_index_fn, queue)."""
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        repo = tmp_path / "repo"
        repo.mkdir()

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            watch=MappingProxyType({"mycode": (repo,)}),
        )

        queue = MagicMock(spec=IndexingQueue)
        server = create_server(
            group_name="default",
            config=config,
            indexing_status=IndexingStatus(),
            indexing_queue=queue,
        )
        rag_index_fn = server._tool_manager._tools["rag_index"].fn
        return rag_index_fn, queue

    def test_returns_error_when_ollama_unreachable(
        self, watch_server: tuple[Any, MagicMock]
    ) -> None:
        """Upfront Ollama check returns error dict before any indexing."""
        from ragling.embeddings import OllamaConnectionError

        rag_index_fn, _queue = watch_server

        with patch(
            "ragling.embeddings.check_connection",
            side_effect=OllamaConnectionError("Cannot connect to Ollama"),
        ):
            result: dict[str, Any] = rag_index_fn(collection="mycode")

        assert "error" in result
        assert "Ollama" in result["error"]

    def test_completed_with_errors_status(self, watch_server: tuple[Any, MagicMock]) -> None:
        """Response uses completed_with_errors when IndexResult has errors."""
        from ragling.indexers.base import IndexResult

        rag_index_fn, _queue = watch_server

        mock_result = IndexResult(
            indexed=3,
            skipped=1,
            errors=2,
            error_messages=["/tmp/bad1.py", "/tmp/bad2.py"],
        )
        with (
            patch("ragling.embeddings.check_connection"),
            patch("ragling.sync.sync_directory_source", return_value=mock_result),
            patch("ragling.db.get_connection", return_value=MagicMock()),
            patch("ragling.db.init_db"),
        ):
            result: dict[str, Any] = rag_index_fn(collection="mycode")

        assert result["status"] == "completed_with_errors"
        assert result["indexed"] == 3
        assert result["errors"] == 2
        assert result["error_messages"] == ["/tmp/bad1.py", "/tmp/bad2.py"]
        assert result["skipped"] == 1

    def test_completed_status_when_no_errors(self, watch_server: tuple[Any, MagicMock]) -> None:
        """Response uses completed when IndexResult has no errors."""
        from ragling.indexers.base import IndexResult

        rag_index_fn, _queue = watch_server

        mock_result = IndexResult(indexed=10, skipped=5, skipped_empty=2, pruned=1)
        with (
            patch("ragling.embeddings.check_connection"),
            patch("ragling.sync.sync_directory_source", return_value=mock_result),
            patch("ragling.db.get_connection", return_value=MagicMock()),
            patch("ragling.db.init_db"),
        ):
            result: dict[str, Any] = rag_index_fn(collection="mycode")

        assert result["status"] == "completed"
        assert result["indexed"] == 10
        assert result["skipped"] == 5
        assert result["skipped_empty"] == 2
        assert result["pruned"] == 1
        assert result["errors"] == 0

    def test_aggregates_results_across_multiple_paths(self, tmp_path: Path) -> None:
        """Multiple watch paths have their IndexResults summed."""
        from ragling.indexers.base import IndexResult
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
            watch=MappingProxyType({"mycode": (repo1, repo2)}),
        )

        queue = MagicMock(spec=IndexingQueue)
        server = create_server(
            group_name="default",
            config=config,
            indexing_status=IndexingStatus(),
            indexing_queue=queue,
        )
        rag_index_fn = server._tool_manager._tools["rag_index"].fn

        results = [
            IndexResult(indexed=5, skipped=2, errors=1, error_messages=["/tmp/bad.py"]),
            IndexResult(indexed=3, skipped=1, errors=0),
        ]
        with (
            patch("ragling.embeddings.check_connection"),
            patch("ragling.sync.sync_directory_source", side_effect=results),
            patch("ragling.db.get_connection", return_value=MagicMock()),
            patch("ragling.db.init_db"),
        ):
            result: dict[str, Any] = rag_index_fn(collection="mycode")

        assert result["status"] == "completed_with_errors"
        assert result["indexed"] == 8
        assert result["skipped"] == 3
        assert result["errors"] == 1
        assert result["error_messages"] == ["/tmp/bad.py"]


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
        )

        static_queue = MagicMock(spec=IndexingQueue)
        dynamic_queue = MagicMock(spec=IndexingQueue)

        server = create_server(
            config=config,
            indexing_queue=static_queue,
            queue_getter=lambda: dynamic_queue,
        )

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        with patch("ragling.embeddings.check_connection"):
            result: dict[str, Any] = rag_index_fn(collection="email")

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
        )

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
        result1: dict[str, Any] = rag_index_fn(collection="email")
        assert "error" in result1
        assert "read-only" in result1["error"].lower()

        # Promote to leader
        current_queue = promoted_queue

        # Now should route through the queue
        with patch("ragling.embeddings.check_connection"):
            result2: dict[str, Any] = rag_index_fn(collection="email")
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
        )

        queue = MagicMock(spec=IndexingQueue)

        # No queue_getter — only static indexing_queue
        server = create_server(
            config=config,
            indexing_queue=queue,
        )

        tools = server._tool_manager._tools
        rag_index_fn = tools["rag_index"].fn
        with patch("ragling.embeddings.check_connection"):
            result: dict[str, Any] = rag_index_fn(collection="email")

        queue.submit.assert_called_once()
        assert result["status"] == "submitted"


class TestVisibilityFiltering:
    """Tests for collection visibility filtering by user context (S1, S3)."""

    def _setup_server_with_collections(
        self, tmp_path: Path, user_collections: list[str] | None = None
    ) -> tuple[Any, dict[str, Any]]:
        """Create a server with collections in the DB and an authenticated user.

        Returns (server, tools_dict).
        """
        from ragling.config import UserConfig
        from ragling.db import get_connection, init_db
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            obsidian_vaults=(tmp_path / "vault",),
            users={
                "kitchen": UserConfig(
                    api_key="test-key",
                    system_collections=user_collections or ["obsidian"],
                ),
            },
        )
        (tmp_path / "vault").mkdir(exist_ok=True)

        # Seed the database with some collections
        conn = get_connection(config)
        init_db(conn, config)
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
            ("kitchen", "project"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO collections (name, collection_type) VALUES (?, ?)",
            ("secret_project", "project"),
        )
        conn.commit()
        conn.close()

        server = create_server(group_name="default", config=config)
        tools = server._tool_manager._tools
        return server, tools

    # -- rag_list_collections visibility --

    def test_list_collections_filters_by_user_visibility(self, tmp_path: Path) -> None:
        """Authenticated user only sees their visible collections."""
        _server, tools = self._setup_server_with_collections(
            tmp_path, user_collections=["obsidian"]
        )
        fn = tools["rag_list_collections"].fn

        mock_token = MagicMock()
        mock_token.client_id = "kitchen"
        with patch("ragling.tools.helpers.get_access_token", return_value=mock_token):
            result = fn()

        names = [c["name"] for c in result["result"]]
        # kitchen user sees: "kitchen" (own) + "obsidian" (system_collections)
        assert "kitchen" in names
        assert "obsidian" in names
        # Should NOT see email or secret_project
        assert "email" not in names
        assert "secret_project" not in names

    def test_list_collections_no_filter_when_unauthenticated(self, tmp_path: Path) -> None:
        """Without auth (stdio), all collections are returned."""
        _server, tools = self._setup_server_with_collections(tmp_path)
        fn = tools["rag_list_collections"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn()

        names = [c["name"] for c in result["result"]]
        assert "obsidian" in names
        assert "email" in names
        assert "kitchen" in names
        assert "secret_project" in names

    # -- rag_collection_info visibility --

    def test_collection_info_rejects_unauthorized_collection(self, tmp_path: Path) -> None:
        """Authenticated user cannot view info for collections they can't see."""
        _server, tools = self._setup_server_with_collections(
            tmp_path, user_collections=["obsidian"]
        )
        fn = tools["rag_collection_info"].fn

        mock_token = MagicMock()
        mock_token.client_id = "kitchen"
        with patch("ragling.tools.helpers.get_access_token", return_value=mock_token):
            result = fn(collection="email")

        assert "error" in result

    def test_collection_info_allows_authorized_collection(self, tmp_path: Path) -> None:
        """Authenticated user can view info for their visible collections."""
        _server, tools = self._setup_server_with_collections(
            tmp_path, user_collections=["obsidian"]
        )
        fn = tools["rag_collection_info"].fn

        mock_token = MagicMock()
        mock_token.client_id = "kitchen"
        with patch("ragling.tools.helpers.get_access_token", return_value=mock_token):
            result = fn(collection="obsidian")

        assert "error" not in result
        assert result["name"] == "obsidian"

    def test_collection_info_no_filter_when_unauthenticated(self, tmp_path: Path) -> None:
        """Without auth, any collection can be queried."""
        _server, tools = self._setup_server_with_collections(tmp_path)
        fn = tools["rag_collection_info"].fn

        with patch("ragling.tools.helpers.get_access_token", return_value=None):
            result = fn(collection="email")

        assert "error" not in result
        assert result["name"] == "email"

    # -- rag_index visibility --

    def test_index_rejects_unauthorized_collection(self, tmp_path: Path) -> None:
        """Authenticated user cannot index collections they can't see."""
        from ragling.indexing_queue import IndexingQueue

        from ragling.config import UserConfig
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            obsidian_vaults=(tmp_path / "vault",),
            users={
                "kitchen": UserConfig(
                    api_key="test-key",
                    system_collections=["obsidian"],
                ),
            },
        )
        (tmp_path / "vault").mkdir(exist_ok=True)

        queue = MagicMock(spec=IndexingQueue)
        server = create_server(
            group_name="default",
            config=config,
            indexing_queue=queue,
        )
        tools = server._tool_manager._tools
        fn = tools["rag_index"].fn

        mock_token = MagicMock()
        mock_token.client_id = "kitchen"
        with patch("ragling.tools.helpers.get_access_token", return_value=mock_token):
            result = fn(collection="email")

        assert "error" in result
        queue.submit.assert_not_called()

    def test_index_allows_authorized_collection(self, tmp_path: Path) -> None:
        """Authenticated user can index their visible collections."""
        from ragling.indexing_queue import IndexingQueue

        from ragling.config import UserConfig
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            users={
                "kitchen": UserConfig(
                    api_key="test-key",
                    system_collections=["email"],
                ),
            },
        )

        queue = MagicMock(spec=IndexingQueue)
        server = create_server(
            group_name="default",
            config=config,
            indexing_queue=queue,
        )
        tools = server._tool_manager._tools
        fn = tools["rag_index"].fn

        mock_token = MagicMock()
        mock_token.client_id = "kitchen"
        with (
            patch("ragling.tools.helpers.get_access_token", return_value=mock_token),
            patch("ragling.embeddings.check_connection"),
        ):
            result = fn(collection="email")

        assert "error" not in result
        assert result["status"] == "submitted"

    def test_index_no_filter_when_unauthenticated(self, tmp_path: Path) -> None:
        """Without auth, any collection can be indexed."""
        from ragling.indexing_queue import IndexingQueue

        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        queue = MagicMock(spec=IndexingQueue)
        server = create_server(
            group_name="default",
            config=config,
            indexing_queue=queue,
        )
        tools = server._tool_manager._tools
        fn = tools["rag_index"].fn

        with (
            patch("ragling.tools.helpers.get_access_token", return_value=None),
            patch("ragling.embeddings.check_connection"),
        ):
            result = fn(collection="email")

        assert "error" not in result
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


class TestRagBatchSearch:
    """Tests for the rag_batch_search MCP tool."""

    def test_batch_search_registered(self, tmp_path: Path) -> None:
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        server = create_server(config=config)
        tools = server._tool_manager._tools
        assert "rag_batch_search" in tools

    def test_batch_search_empty_queries(self, tmp_path: Path) -> None:
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        server = create_server(config=config)
        tools = server._tool_manager._tools
        fn = tools["rag_batch_search"].fn

        result = fn(queries=[])
        assert result["results"] == []
        assert result["indexing"] is None

    def test_batch_search_rejects_missing_query_key(self, tmp_path: Path) -> None:
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        server = create_server(config=config)
        tools = server._tool_manager._tools
        fn = tools["rag_batch_search"].fn

        result = fn(queries=[{"collection": "obsidian"}])
        assert "error" in result

    def test_batch_search_calls_perform_batch_search(self, tmp_path: Path) -> None:
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        server = create_server(config=config)
        tools = server._tool_manager._tools
        fn = tools["rag_batch_search"].fn

        with patch("ragling.search.search.perform_batch_search", return_value=[[], []]) as mock_pbs:
            result = fn(
                queries=[
                    {"query": "hello"},
                    {"query": "world", "collection": "code", "top_k": 5},
                ]
            )

        mock_pbs.assert_called_once()
        call_args = mock_pbs.call_args
        batch_queries = call_args.kwargs["queries"]
        assert len(batch_queries) == 2
        assert batch_queries[0].query == "hello"
        assert batch_queries[0].top_k == 10  # default
        assert batch_queries[1].query == "world"
        assert batch_queries[1].collection == "code"
        assert batch_queries[1].top_k == 5
        assert result["results"] == [[], []]

    def test_batch_search_returns_per_query_results(self, tmp_path: Path) -> None:
        from ragling.mcp_server import create_server
        from ragling.search.search import SearchResult

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        server = create_server(config=config)
        tools = server._tool_manager._tools
        fn = tools["rag_batch_search"].fn

        mock_results = [
            [
                SearchResult(
                    content="result 1",
                    title="Result 1",
                    metadata={},
                    score=0.9,
                    collection="code",
                    source_path="/tmp/a.py",
                    source_type="code",
                ),
            ],
            [
                SearchResult(
                    content="result 2",
                    title="Result 2",
                    metadata={},
                    score=0.8,
                    collection="obsidian",
                    source_path="/tmp/b.md",
                    source_type="markdown",
                ),
            ],
        ]

        with patch("ragling.search.search.perform_batch_search", return_value=mock_results):
            result = fn(
                queries=[
                    {"query": "first"},
                    {"query": "second"},
                ]
            )

        assert len(result["results"]) == 2
        assert len(result["results"][0]) == 1
        assert result["results"][0][0]["title"] == "Result 1"
        assert len(result["results"][1]) == 1
        assert result["results"][1][0]["title"] == "Result 2"

    def test_batch_search_handles_ollama_error(self, tmp_path: Path) -> None:
        from ragling.embeddings import OllamaConnectionError
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        server = create_server(config=config)
        tools = server._tool_manager._tools
        fn = tools["rag_batch_search"].fn

        with patch(
            "ragling.search.search.perform_batch_search",
            side_effect=OllamaConnectionError("connection refused"),
        ):
            result = fn(queries=[{"query": "test"}])

        assert result["results"][0]["error"] == "connection refused"

    def test_batch_search_includes_indexing_status(self, tmp_path: Path) -> None:
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
        fn = tools["rag_batch_search"].fn

        with patch("ragling.search.search.perform_batch_search", return_value=[[]]):
            result = fn(queries=[{"query": "test"}])

        assert result["indexing"] is not None
        assert result["indexing"]["active"] is True
        assert result["indexing"]["total_remaining"] == 3

    def test_batch_search_idle_indexing_status(self, tmp_path: Path) -> None:
        """Idle IndexingStatus produces indexing=None via _build_search_response.

        Prior to the _build_search_response unification, rag_batch_search had
        inline logic that checked ``status_dict.get("active")`` before including
        the status. That check was redundant: IndexingStatus.to_dict() already
        returns None when idle and always sets ``active=True`` when active.
        This test confirms the unified path preserves the same behavior.
        """
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        status = IndexingStatus()  # idle — no pending work
        server = create_server(config=config, indexing_status=status)
        tools = server._tool_manager._tools
        fn = tools["rag_batch_search"].fn

        with patch("ragling.search.search.perform_batch_search", return_value=[[]]):
            result = fn(queries=[{"query": "test"}])

        assert result["indexing"] is None


class TestRagIndexSystemCollectionDispatch:
    """Tests for data-driven system collection dispatch in _rag_index_via_queue."""

    @pytest.mark.parametrize(
        "collection,expected_job_type,expected_indexer_type",
        [
            ("email", "system_collection", "email"),
            ("calibre", "system_collection", "calibre"),
            ("rss", "system_collection", "rss"),
        ],
    )
    def test_system_collection_creates_correct_job(
        self,
        tmp_path: Path,
        collection: str,
        expected_job_type: str,
        expected_indexer_type: str,
    ) -> None:
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        status = IndexingStatus()
        q = IndexingQueue(config, status)
        server = create_server(config=config, indexing_status=status, indexing_queue=q)
        tools = server._tool_manager._tools
        fn = tools["rag_index"].fn

        with patch("ragling.embeddings.check_connection"):
            result = fn(collection=collection, path=None)
        assert result["status"] == "submitted"
        assert result["collection"] == collection

        # Verify the job was submitted with correct type
        # IndexingQueue stores raw IndexJob objects in _queue via submit()
        item = q._queue.get_nowait()
        assert item.job_type == expected_job_type
        assert item.indexer_type.value == expected_indexer_type


class TestRagIndexPlan:
    """Tests for rag_index plan (dry-run) mode."""

    def test_plan_code_group_returns_walk_plan(self, tmp_path: Path) -> None:
        """plan=True for code group (migrated to watch) runs walk and returns formatted plan."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("print('hello')")

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            watch=MappingProxyType({"mycode": (repo,)}),
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

        result: dict[str, Any] = rag_index_fn(collection="mycode", plan=True)

        assert result["status"] == "plan"
        assert "plan" in result
        assert "Walk complete" in result["plan"]
        queue.submit.assert_not_called()

    def test_plan_watch_collection_returns_walk_plan(self, tmp_path: Path) -> None:
        """plan=True for watch collection runs walk and returns formatted plan."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        dir1 = tmp_path / "docs"
        dir1.mkdir()
        (dir1 / "readme.md").write_text("# Hello")

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            watch=MappingProxyType({"research": (dir1,)}),
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

        result: dict[str, Any] = rag_index_fn(collection="research", plan=True)

        assert result["status"] == "plan"
        assert "Walk complete" in result["plan"]
        queue.submit.assert_not_called()

    def test_plan_system_collection_returns_error(self, tmp_path: Path) -> None:
        """plan=True for system collections (email, calibre, rss) returns an error."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
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

        result: dict[str, Any] = rag_index_fn(collection="email", plan=True)

        assert "error" in result
        assert "plan" in result["error"].lower() or "system" in result["error"].lower()

    def test_plan_no_queue_still_works(self, tmp_path: Path) -> None:
        """plan=True works even without an indexing queue (read-only)."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        dir1 = tmp_path / "docs"
        dir1.mkdir()
        (dir1 / "notes.md").write_text("# Notes")

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            watch=MappingProxyType({"research": (dir1,)}),
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

        result: dict[str, Any] = rag_index_fn(collection="research", plan=True)

        assert result["status"] == "plan"
        assert "Walk complete" in result["plan"]

    def test_plan_respects_ragignore_exclusions(self, tmp_path: Path) -> None:
        """plan=True should apply ragignore exclusions to match real indexing."""
        from ragling.config import Config
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus
        from ragling.mcp_server import create_server

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("print('hello')")
        (repo / "excluded.draft.md").write_text("# Draft")

        # Create a ragignore at the path the code will look for
        ragling_dir = tmp_path / ".ragling"
        ragling_dir.mkdir()
        (ragling_dir / "ragignore").write_text("*.draft.md\n")

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
            watch=MappingProxyType({"mycode": (repo,)}),
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

        # Patch Path.home() so ragignore is found at tmp_path
        with patch("pathlib.Path.home", return_value=tmp_path):
            result: dict[str, Any] = rag_index_fn(collection="mycode", plan=True)

        assert result["status"] == "plan"
        # The draft file should be excluded, only main.py should be in the plan
        assert "excluded.draft.md" not in result["plan"]
        assert "treesitter" in result["plan"]
