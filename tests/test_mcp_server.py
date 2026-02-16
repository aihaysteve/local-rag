"""Tests for ragling.mcp_server module."""


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
        status.set_remaining(5)
        response = _build_search_response([], status)
        assert response["indexing"] == {"active": True, "remaining": 5}

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
