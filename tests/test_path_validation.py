"""Tests for path validation in rag_convert (S2 security fix)."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from unittest.mock import MagicMock, patch

from ragling.config import Config, UserConfig


class TestGetAllowedPaths:
    """Tests for _get_allowed_paths collecting all configured source directories."""

    def test_includes_obsidian_vaults(self, tmp_path: Path) -> None:
        from ragling.mcp_server import _get_allowed_paths

        vault = tmp_path / "vault"
        vault.mkdir()
        config = Config(obsidian_vaults=(vault,))
        allowed = _get_allowed_paths(config)
        assert vault.resolve() in allowed

    def test_includes_calibre_libraries(self, tmp_path: Path) -> None:
        from ragling.mcp_server import _get_allowed_paths

        lib = tmp_path / "calibre"
        lib.mkdir()
        config = Config(calibre_libraries=(lib,))
        allowed = _get_allowed_paths(config)
        assert lib.resolve() in allowed

    def test_includes_code_group_repo_paths(self, tmp_path: Path) -> None:
        from ragling.mcp_server import _get_allowed_paths

        repo1 = tmp_path / "repo1"
        repo2 = tmp_path / "repo2"
        repo1.mkdir()
        repo2.mkdir()
        config = Config(code_groups=MappingProxyType({"mygroup": (repo1, repo2)}))
        allowed = _get_allowed_paths(config)
        assert repo1.resolve() in allowed
        assert repo2.resolve() in allowed

    def test_includes_home_when_set(self, tmp_path: Path) -> None:
        from ragling.mcp_server import _get_allowed_paths

        home = tmp_path / "home"
        home.mkdir()
        config = Config(home=home)
        allowed = _get_allowed_paths(config)
        assert home.resolve() in allowed

    def test_excludes_home_when_none(self) -> None:
        from ragling.mcp_server import _get_allowed_paths

        config = Config(home=None)
        allowed = _get_allowed_paths(config)
        # Should not crash and should return a list (possibly empty)
        assert isinstance(allowed, list)

    def test_includes_global_paths(self, tmp_path: Path) -> None:
        from ragling.mcp_server import _get_allowed_paths

        gp1 = tmp_path / "global1"
        gp2 = tmp_path / "global2"
        gp1.mkdir()
        gp2.mkdir()
        config = Config(global_paths=(gp1, gp2))
        allowed = _get_allowed_paths(config)
        assert gp1.resolve() in allowed
        assert gp2.resolve() in allowed

    def test_combines_all_sources(self, tmp_path: Path) -> None:
        from ragling.mcp_server import _get_allowed_paths

        vault = tmp_path / "vault"
        lib = tmp_path / "calibre"
        repo = tmp_path / "repo"
        home = tmp_path / "home"
        gp = tmp_path / "global"
        for d in (vault, lib, repo, home, gp):
            d.mkdir()

        config = Config(
            obsidian_vaults=(vault,),
            calibre_libraries=(lib,),
            code_groups=MappingProxyType({"grp": (repo,)}),
            home=home,
            global_paths=(gp,),
        )
        allowed = _get_allowed_paths(config)
        assert len(allowed) == 5
        assert vault.resolve() in allowed
        assert lib.resolve() in allowed
        assert repo.resolve() in allowed
        assert home.resolve() in allowed
        assert gp.resolve() in allowed

    def test_empty_config_returns_empty(self) -> None:
        from ragling.mcp_server import _get_allowed_paths

        config = Config()
        allowed = _get_allowed_paths(config)
        assert allowed == []

    def test_multiple_code_groups(self, tmp_path: Path) -> None:
        from ragling.mcp_server import _get_allowed_paths

        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_c = tmp_path / "c"
        for d in (repo_a, repo_b, repo_c):
            d.mkdir()

        config = Config(
            code_groups=MappingProxyType(
                {
                    "group1": (repo_a, repo_b),
                    "group2": (repo_c,),
                }
            )
        )
        allowed = _get_allowed_paths(config)
        assert repo_a.resolve() in allowed
        assert repo_b.resolve() in allowed
        assert repo_c.resolve() in allowed


class TestConvertDocumentPathRestriction:
    """Tests for restrict_paths parameter on _convert_document."""

    def test_allows_file_within_allowed_path(self, tmp_path: Path) -> None:
        """File inside an allowed directory is permitted."""
        from ragling.mcp_server import _convert_document

        vault = tmp_path / "vault"
        vault.mkdir()
        md_file = vault / "note.md"
        md_file.write_text("# Allowed")

        config = Config(obsidian_vaults=(vault,))
        result = _convert_document(
            str(md_file), path_mappings={}, restrict_paths=True, config=config
        )
        assert "Allowed" in result

    def test_rejects_file_outside_allowed_paths(self, tmp_path: Path) -> None:
        """File outside all allowed directories is rejected."""
        from ragling.mcp_server import _convert_document

        vault = tmp_path / "vault"
        vault.mkdir()
        secret = tmp_path / "secret"
        secret.mkdir()
        secret_file = secret / "passwords.md"
        secret_file.write_text("super secret")

        config = Config(obsidian_vaults=(vault,))
        result = _convert_document(
            str(secret_file), path_mappings={}, restrict_paths=True, config=config
        )
        assert "error" in result.lower()
        assert "not accessible" in result.lower()
        # Must NOT contain the actual content
        assert "super secret" not in result

    def test_no_restriction_when_restrict_paths_false(self, tmp_path: Path) -> None:
        """When restrict_paths=False, any file is accessible (stdio mode)."""
        from ragling.mcp_server import _convert_document

        vault = tmp_path / "vault"
        vault.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        file = outside / "note.md"
        file.write_text("# Unrestricted")

        config = Config(obsidian_vaults=(vault,))
        result = _convert_document(str(file), path_mappings={}, restrict_paths=False, config=config)
        assert "Unrestricted" in result

    def test_default_restrict_paths_is_false(self, tmp_path: Path) -> None:
        """Default behavior (no restrict_paths) allows any file (backwards compat)."""
        from ragling.mcp_server import _convert_document

        outside = tmp_path / "anywhere"
        outside.mkdir()
        file = outside / "note.md"
        file.write_text("# Default allowed")

        result = _convert_document(str(file), path_mappings={})
        assert "Default allowed" in result

    def test_rejects_symlink_escape(self, tmp_path: Path) -> None:
        """Symlink pointing outside allowed paths is rejected."""
        from ragling.mcp_server import _convert_document

        vault = tmp_path / "vault"
        vault.mkdir()
        secret = tmp_path / "secret"
        secret.mkdir()
        secret_file = secret / "data.md"
        secret_file.write_text("secret data")

        # Create symlink inside vault pointing outside
        link = vault / "escape.md"
        link.symlink_to(secret_file)

        config = Config(obsidian_vaults=(vault,))
        result = _convert_document(str(link), path_mappings={}, restrict_paths=True, config=config)
        assert "error" in result.lower()
        assert "not accessible" in result.lower()

    def test_allows_nested_file_in_allowed_path(self, tmp_path: Path) -> None:
        """File in a subdirectory of an allowed path is permitted."""
        from ragling.mcp_server import _convert_document

        vault = tmp_path / "vault"
        sub = vault / "sub" / "deep"
        sub.mkdir(parents=True)
        file = sub / "note.md"
        file.write_text("# Deep")

        config = Config(obsidian_vaults=(vault,))
        result = _convert_document(str(file), path_mappings={}, restrict_paths=True, config=config)
        assert "Deep" in result

    def test_restriction_with_path_mapping(self, tmp_path: Path) -> None:
        """Path mapping is applied before restriction check (uses host path)."""
        from ragling.mcp_server import _convert_document

        vault = tmp_path / "vault"
        vault.mkdir()
        md_file = vault / "note.md"
        md_file.write_text("# Mapped and Allowed")

        config = Config(obsidian_vaults=(vault,))
        mappings = {str(vault) + "/": "/container/vault/"}
        result = _convert_document(
            "/container/vault/note.md",
            path_mappings=mappings,
            restrict_paths=True,
            config=config,
        )
        assert "Mapped and Allowed" in result

    def test_restriction_rejects_mapped_path_outside_allowed(self, tmp_path: Path) -> None:
        """Even with mapping, the host path must be within allowed directories."""
        from ragling.mcp_server import _convert_document

        vault = tmp_path / "vault"
        vault.mkdir()
        secret = tmp_path / "secret"
        secret.mkdir()
        secret_file = secret / "data.md"
        secret_file.write_text("secret")

        config = Config(obsidian_vaults=(vault,))
        # Mapping resolves to secret/ which is outside vault/
        mappings = {str(secret) + "/": "/container/mapped/"}
        result = _convert_document(
            "/container/mapped/data.md",
            path_mappings=mappings,
            restrict_paths=True,
            config=config,
        )
        assert "error" in result.lower()
        assert "not accessible" in result.lower()

    def test_generic_error_message_no_path_leak(self, tmp_path: Path) -> None:
        """Error message should be generic and not reveal the actual resolved path."""
        from ragling.mcp_server import _convert_document

        vault = tmp_path / "vault"
        vault.mkdir()
        secret = tmp_path / "very_secret_dir"
        secret.mkdir()
        secret_file = secret / "data.md"
        secret_file.write_text("x")

        config = Config(obsidian_vaults=(vault,))
        result = _convert_document(
            str(secret_file), path_mappings={}, restrict_paths=True, config=config
        )
        assert "very_secret_dir" not in result
        assert result == "Error: file not accessible"


class TestRagConvertPassesRestrictPaths:
    """Tests that rag_convert passes restrict_paths=True when user context is present."""

    def test_rag_convert_restricts_when_user_context_present(self, tmp_path: Path) -> None:
        """When user context is present (SSE mode), restrict_paths=True."""
        from ragling.mcp_server import create_server

        vault = tmp_path / "vault"
        vault.mkdir()
        secret = tmp_path / "secret"
        secret.mkdir()
        secret_file = secret / "passwords.md"
        secret_file.write_text("super secret")

        config = Config(
            obsidian_vaults=(vault,),
            users={"testuser": UserConfig(api_key="key123")},
        )

        server = create_server(group_name="default", config=config)
        tools = server._tool_manager._tools
        rag_convert_fn = tools["rag_convert"].fn

        # Simulate authenticated user context
        mock_token = MagicMock()
        mock_token.client_id = "testuser"
        with patch("ragling.mcp_server.get_access_token", return_value=mock_token):
            result = rag_convert_fn(file_path=str(secret_file))

        assert "error" in result.lower()
        assert "not accessible" in result.lower()
        assert "super secret" not in result

    def test_rag_convert_no_restriction_without_user_context(self, tmp_path: Path) -> None:
        """When no user context (stdio mode), restrict_paths=False."""
        from ragling.mcp_server import create_server

        anywhere = tmp_path / "anywhere"
        anywhere.mkdir()
        file = anywhere / "note.md"
        file.write_text("# No restriction")

        config = Config()  # no users configured

        server = create_server(group_name="default", config=config)
        tools = server._tool_manager._tools
        rag_convert_fn = tools["rag_convert"].fn

        # No authenticated user -> _get_user_context returns None
        with patch("ragling.mcp_server.get_access_token", return_value=None):
            result = rag_convert_fn(file_path=str(file))

        assert "No restriction" in result

    def test_rag_convert_allows_file_in_allowed_path_with_user_context(
        self, tmp_path: Path
    ) -> None:
        """Authenticated user can access files within configured paths."""
        from ragling.mcp_server import create_server

        vault = tmp_path / "vault"
        vault.mkdir()
        file = vault / "allowed.md"
        file.write_text("# Allowed content")

        config = Config(
            obsidian_vaults=(vault,),
            users={"testuser": UserConfig(api_key="key123")},
        )

        server = create_server(group_name="default", config=config)
        tools = server._tool_manager._tools
        rag_convert_fn = tools["rag_convert"].fn

        mock_token = MagicMock()
        mock_token.client_id = "testuser"
        with patch("ragling.mcp_server.get_access_token", return_value=mock_token):
            result = rag_convert_fn(file_path=str(file))

        assert "Allowed content" in result
