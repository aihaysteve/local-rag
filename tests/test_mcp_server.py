"""Tests for ragling.mcp_server module."""

from pathlib import Path
from unittest.mock import MagicMock, patch


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
