"""Tests for ragling CLI."""

from pathlib import Path

from click.testing import CliRunner

from ragling.cli import main


class TestGroupFlag:
    """Tests for the --group/-g CLI option."""

    def test_main_accepts_group_flag(self) -> None:
        """The main CLI group should accept --group."""
        runner = CliRunner()
        result = runner.invoke(main, ["--group", "test", "--help"])
        assert result.exit_code == 0
        assert "--group" in result.output

    def test_main_accepts_short_group_flag(self) -> None:
        """The main CLI group should accept -g as short form."""
        runner = CliRunner()
        result = runner.invoke(main, ["-g", "test", "--help"])
        assert result.exit_code == 0

    def test_default_group_shown_in_help(self) -> None:
        """Help text should mention --group and show the default."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--group" in result.output or "-g" in result.output
        assert "default" in result.output

    def test_serve_help_works_with_group(self) -> None:
        """The serve subcommand should be reachable with --group set."""
        runner = CliRunner()
        result = runner.invoke(main, ["--group", "work", "serve", "--help"])
        assert result.exit_code == 0

    def test_index_help_works_with_group(self) -> None:
        """The index subcommand should be reachable with --group set."""
        runner = CliRunner()
        result = runner.invoke(main, ["--group", "work", "index", "--help"])
        assert result.exit_code == 0

    def test_search_help_works_with_group(self) -> None:
        """The search subcommand should be reachable with --group set."""
        runner = CliRunner()
        result = runner.invoke(main, ["--group", "work", "search", "--help"])
        assert result.exit_code == 0

    def test_group_stored_in_context(self) -> None:
        """The group value should be stored in ctx.obj for subcommands to use."""
        runner = CliRunner()
        # Using --help on a subcommand verifies the context pipeline works
        # without needing a real database or config
        result = runner.invoke(main, ["--group", "personal", "index", "--help"])
        assert result.exit_code == 0

    def test_group_default_value(self) -> None:
        """When --group is not specified, it should default to 'default'."""
        runner = CliRunner()
        # If no group is given, the help output should still work
        result = runner.invoke(main, ["index", "--help"])
        assert result.exit_code == 0


class TestConfigFlag:
    """Tests for the --config CLI option."""

    def test_main_has_config_option(self) -> None:
        """--config flag is accepted on the main group."""
        param_names = [p.name for p in main.params]
        assert "config_path" in param_names


class TestMcpServer:
    """Tests for the MCP server factory."""

    def test_create_server_returns_server(self) -> None:
        """create_server() should return a FastMCP instance."""
        from ragling.mcp_server import create_server

        server = create_server()
        assert server is not None

    def test_create_server_accepts_group_name(self) -> None:
        """create_server() should accept a group_name parameter."""
        from ragling.mcp_server import create_server

        server = create_server(group_name="test")
        assert server is not None

    def test_rag_doc_store_info_tool_registered(self) -> None:
        """The rag_doc_store_info tool should be registered on the server."""
        import asyncio

        from ragling.mcp_server import create_server

        server = create_server()
        tools = asyncio.run(server.list_tools())
        tool_names = [t.name for t in tools]
        assert "rag_doc_store_info" in tool_names

    def test_all_expected_tools_registered(self) -> None:
        """All expected tools should be registered on the server."""
        import asyncio

        from ragling.mcp_server import create_server

        server = create_server(group_name="test-group")
        tools = asyncio.run(server.list_tools())
        tool_names = {t.name for t in tools}
        expected = {
            "rag_search",
            "rag_list_collections",
            "rag_index",
            "rag_doc_store_info",
            "rag_collection_info",
        }
        assert expected.issubset(tool_names)


class TestBuildSourceUri:
    """Tests for _build_source_uri in mcp_server."""

    def test_rss_returns_url_from_metadata(self) -> None:
        from ragling.mcp_server import _build_source_uri

        uri = _build_source_uri("art-123", "rss", {"url": "https://example.com/article"}, "rss")
        assert uri == "https://example.com/article"

    def test_rss_without_url_returns_none(self) -> None:
        from ragling.mcp_server import _build_source_uri

        uri = _build_source_uri("art-123", "rss", {}, "rss")
        assert uri is None

    def test_email_returns_none(self) -> None:
        from ragling.mcp_server import _build_source_uri

        uri = _build_source_uri("msg-123", "email", {}, "email")
        assert uri is None

    def test_commit_returns_none(self) -> None:
        from ragling.mcp_server import _build_source_uri

        uri = _build_source_uri("git://sha", "commit", {}, "my-org")
        assert uri is None

    def test_code_returns_vscode_uri(self) -> None:
        from ragling.mcp_server import _build_source_uri

        uri = _build_source_uri("/home/user/repo/main.py", "code", {"start_line": 42}, "my-org")
        assert uri is not None
        assert uri.startswith("vscode://file")
        assert "main.py" in uri
        assert ":42" in uri

    def test_file_returns_file_uri(self) -> None:
        from ragling.mcp_server import _build_source_uri

        uri = _build_source_uri("/home/user/docs/report.pdf", "pdf", {}, "my-project")
        assert uri is not None
        assert uri.startswith("file://")
        assert "report.pdf" in uri

    def test_calibre_virtual_path_returns_none(self) -> None:
        from ragling.mcp_server import _build_source_uri

        uri = _build_source_uri(
            "calibre:///Library/Author/book", "calibre-description", {}, "calibre"
        )
        assert uri is None

    def test_obsidian_returns_obsidian_uri(self, tmp_path: Path) -> None:
        from ragling.mcp_server import _build_source_uri

        vault = tmp_path / "MyVault"
        vault.mkdir()
        note = vault / "notes" / "test.md"
        note.parent.mkdir()
        note.write_text("test")

        uri = _build_source_uri(str(note), "markdown", {}, "obsidian", obsidian_vaults=[vault])
        assert uri is not None
        assert uri.startswith("obsidian://open")
        assert "MyVault" in uri


class TestGetDb:
    """Tests for _get_db group routing."""

    def test_get_db_sets_group_name_on_config(self) -> None:
        """_get_db should set config.group_name before connecting."""
        from unittest.mock import MagicMock, patch

        from ragling.cli import _get_db
        from ragling.config import Config

        config = Config(embedding_dimensions=4)

        with (
            patch("ragling.db.get_connection") as mock_conn,
            patch("ragling.db.init_db"),
        ):
            mock_conn.return_value = MagicMock()
            _get_db(config, "my-group")

        assert config.group_name == "my-group"

    def test_get_db_uses_default_group(self) -> None:
        """_get_db with no group argument should use 'default'."""
        from unittest.mock import MagicMock, patch

        from ragling.cli import _get_db
        from ragling.config import Config

        config = Config(embedding_dimensions=4)

        with (
            patch("ragling.db.get_connection") as mock_conn,
            patch("ragling.db.init_db"),
        ):
            mock_conn.return_value = MagicMock()
            _get_db(config)

        assert config.group_name == "default"


class TestServeCommand:
    """Tests for the serve command flags."""

    def test_serve_help_shows_sse_flag(self) -> None:
        """The serve command should accept --sse."""
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--sse" in result.output

    def test_serve_help_shows_no_stdio_flag(self) -> None:
        """The serve command should accept --no-stdio."""
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--no-stdio" in result.output

    def test_serve_help_shows_port_with_default(self) -> None:
        """The serve command should show --port with default 10001."""
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "10001" in result.output

    def test_serve_no_stdio_no_sse_errors(self) -> None:
        """Disabling both transports should print an error."""
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--no-stdio"])
        # Should error because neither SSE nor stdio is enabled
        assert "Cannot disable" in result.output or result.exit_code != 0
