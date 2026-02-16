"""Tests for ragling.auth module."""

from ragling.config import Config, UserConfig


class TestResolveApiKey:
    """Tests for resolving API key to user context."""

    def test_valid_key_returns_user_context(self) -> None:
        from ragling.auth import resolve_api_key

        config = Config(
            home=None,
            users={"kitchen": UserConfig(api_key="rag_test123")},
        )
        ctx = resolve_api_key("rag_test123", config)
        assert ctx is not None
        assert ctx.username == "kitchen"

    def test_invalid_key_returns_none(self) -> None:
        from ragling.auth import resolve_api_key

        config = Config(
            users={"kitchen": UserConfig(api_key="rag_test123")},
        )
        assert resolve_api_key("rag_wrong", config) is None

    def test_empty_key_returns_none(self) -> None:
        from ragling.auth import resolve_api_key

        config = Config()
        assert resolve_api_key("", config) is None

    def test_no_users_configured_returns_none(self) -> None:
        from ragling.auth import resolve_api_key

        config = Config()
        assert resolve_api_key("rag_anything", config) is None


class TestUserContextVisibleCollections:
    """Tests for computing visible collections from user config."""

    def test_includes_username_collection(self) -> None:
        from ragling.auth import UserContext

        ctx = UserContext(username="kitchen", system_collections=[], path_mappings={})
        visible = ctx.visible_collections(global_collection="global")
        assert "kitchen" in visible

    def test_includes_global_collection(self) -> None:
        from ragling.auth import UserContext

        ctx = UserContext(username="kitchen", system_collections=[], path_mappings={})
        visible = ctx.visible_collections(global_collection="global")
        assert "global" in visible

    def test_includes_system_collections(self) -> None:
        from ragling.auth import UserContext

        ctx = UserContext(
            username="kitchen",
            system_collections=["obsidian", "calibre"],
            path_mappings={},
        )
        visible = ctx.visible_collections(global_collection="global")
        assert "obsidian" in visible
        assert "calibre" in visible

    def test_no_global_when_no_global_paths(self) -> None:
        from ragling.auth import UserContext

        ctx = UserContext(username="kitchen", system_collections=[], path_mappings={})
        visible = ctx.visible_collections(global_collection=None)
        assert "kitchen" in visible
        assert len(visible) == 1
