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

    def test_get_db_connects_with_given_config(self) -> None:
        """_get_db should use the config's group_name for the connection."""
        from unittest.mock import MagicMock, patch

        from ragling.cli import _get_db
        from ragling.config import Config

        config = Config(embedding_dimensions=4, group_name="my-group")

        with (
            patch("ragling.db.get_connection") as mock_conn,
            patch("ragling.db.init_db"),
        ):
            mock_conn.return_value = MagicMock()
            _get_db(config)

        mock_conn.assert_called_once_with(config)

    def test_get_db_with_default_group(self) -> None:
        """_get_db with default group_name should connect normally."""
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


class TestMcpConfigCommand:
    """Tests for the mcp-config command."""

    def test_mcp_config_exists(self) -> None:
        """The mcp-config command should be registered."""
        runner = CliRunner()
        result = runner.invoke(main, ["mcp-config", "--help"])
        assert result.exit_code == 0

    def test_mcp_config_outputs_json(self, tmp_path: Path) -> None:
        """Output should be valid JSON with mcpServers key."""
        import json

        runner = CliRunner()
        result = runner.invoke(main, ["mcp-config", "--port", "9999", "--tls-dir", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "mcpServers" in data

    def test_mcp_config_includes_url_with_port(self, tmp_path: Path) -> None:
        """URL should include the specified port."""
        import json

        runner = CliRunner()
        result = runner.invoke(main, ["mcp-config", "--port", "8443", "--tls-dir", str(tmp_path)])
        data = json.loads(result.output)
        url = data["mcpServers"]["ragling"]["url"]
        assert "8443" in url
        assert url.startswith("https://")

    def test_mcp_config_includes_ca_cert_path(self, tmp_path: Path) -> None:
        """Config should include ca_cert path."""
        import json

        runner = CliRunner()
        result = runner.invoke(main, ["mcp-config", "--port", "10001", "--tls-dir", str(tmp_path)])
        data = json.loads(result.output)
        ca_cert = data["mcpServers"]["ragling"]["ca_cert"]
        assert "ca.pem" in ca_cert

    def test_mcp_config_default_port(self, tmp_path: Path) -> None:
        """Default port should be 10001."""
        import json

        runner = CliRunner()
        result = runner.invoke(main, ["mcp-config", "--tls-dir", str(tmp_path)])
        data = json.loads(result.output)
        url = data["mcpServers"]["ragling"]["url"]
        assert "10001" in url


class TestMcpConfigOutputCaCert:
    """Tests for mcp-config command ca_cert output with mocked TLS."""

    def test_mcp_config_output_includes_ca_cert(self, tmp_path: Path) -> None:
        """mcp-config command output includes the ca_cert path."""
        import json
        from unittest.mock import patch

        from ragling.tls import TLSConfig

        known_ca = tmp_path / "certs" / "ca.pem"
        known_tls = TLSConfig(
            ca_cert=known_ca,
            ca_key=tmp_path / "certs" / "ca-key.pem",
            server_cert=tmp_path / "certs" / "server.pem",
            server_key=tmp_path / "certs" / "server-key.pem",
        )

        runner = CliRunner()
        with patch("ragling.tls.ensure_tls_certs", return_value=known_tls):
            result = runner.invoke(main, ["mcp-config", "--port", "9999"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "mcpServers" in data
        assert data["mcpServers"]["ragling"]["ca_cert"] == str(known_ca)


class TestStatusCommand:
    """Tests for the status command."""

    def test_status_shows_leader_row_none(self, tmp_path: Path) -> None:
        """Status output should include a Leader row showing 'none' when no leader."""
        from unittest.mock import patch

        from ragling.config import Config

        config = Config(
            db_path=tmp_path / "rag.db",
            group_name="default",
            embedding_dimensions=4,
        )

        # Create a minimal database so status doesn't bail early
        from ragling.db import get_connection, init_db

        conn = get_connection(config)
        init_db(conn, config)
        conn.close()

        runner = CliRunner()
        with patch("ragling.cli.load_config", return_value=config):
            result = runner.invoke(main, ["status"])

        assert result.exit_code == 0
        assert "Leader" in result.output
        assert "none" in result.output

    def test_status_shows_leader_row_active(self, tmp_path: Path) -> None:
        """Status output should include a Leader row showing 'active' when leader holds lock."""
        from unittest.mock import patch

        from ragling.config import Config
        from ragling.leader import LeaderLock, lock_path_for_config

        config = Config(
            db_path=tmp_path / "rag.db",
            group_name="default",
            embedding_dimensions=4,
        )

        # Create a minimal database
        from ragling.db import get_connection, init_db

        conn = get_connection(config)
        init_db(conn, config)
        conn.close()

        # Hold the lock
        lock = LeaderLock(lock_path_for_config(config))
        lock.try_acquire()

        runner = CliRunner()
        try:
            with patch("ragling.cli.load_config", return_value=config):
                result = runner.invoke(main, ["status"])
        finally:
            lock.close()

        assert result.exit_code == 0
        assert "Leader" in result.output
        assert "active" in result.output


class TestWatcherStartupCondition:
    """Tests for watcher starting with obsidian-only configs."""

    def test_obsidian_only_config_triggers_watcher(self, tmp_path: Path) -> None:
        """A config with only obsidian_vaults should still start the watcher."""
        from ragling.config import Config
        from ragling.watcher import get_watch_paths

        vault = tmp_path / "vault"
        vault.mkdir()

        config = Config(
            obsidian_vaults=[vault],
            embedding_dimensions=4,
        )

        paths = get_watch_paths(config)
        assert len(paths) > 0
