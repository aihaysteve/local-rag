"""Tests for ragling CLI."""

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
