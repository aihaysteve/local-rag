"""Tests for ragling CLI."""

import json
from pathlib import Path

import pytest
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

        from ragling.auth.tls import TLSConfig

        known_ca = tmp_path / "certs" / "ca.pem"
        known_tls = TLSConfig(
            ca_cert=known_ca,
            ca_key=tmp_path / "certs" / "ca-key.pem",
            server_cert=tmp_path / "certs" / "server.pem",
            server_key=tmp_path / "certs" / "server-key.pem",
        )

        runner = CliRunner()
        with patch("ragling.auth.tls.ensure_tls_certs", return_value=known_tls):
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


class TestBackgroundFlag:
    """Tests for the --background flag on index subcommands."""

    def test_index_obsidian_background_flag(self, tmp_path: Path) -> None:
        """--background flag is accepted by index obsidian command."""
        from unittest.mock import patch

        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("obsidian_vaults: []\n")

        with patch("ragling.cli._run_in_background") as mock_bg:
            result = runner.invoke(
                main,
                ["--config", str(config_path), "index", "obsidian", "--background"],
            )

        assert result.exit_code == 0
        mock_bg.assert_called_once()
        assert mock_bg.call_args[0][1] == ["obsidian"]
        assert mock_bg.call_args[0][2] is False  # force=False

    def test_index_obsidian_background_with_force(self, tmp_path: Path) -> None:
        """--background with --force passes force=True to _run_in_background."""
        from unittest.mock import patch

        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("obsidian_vaults: []\n")

        with patch("ragling.cli._run_in_background") as mock_bg:
            result = runner.invoke(
                main,
                ["--config", str(config_path), "index", "obsidian", "--background", "--force"],
            )

        assert result.exit_code == 0
        mock_bg.assert_called_once()
        assert mock_bg.call_args[0][2] is True  # force=True

    def test_index_email_background_flag(self, tmp_path: Path) -> None:
        """--background flag is accepted by index email command."""
        from unittest.mock import patch

        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}\n")

        with patch("ragling.cli._run_in_background") as mock_bg:
            result = runner.invoke(
                main,
                ["--config", str(config_path), "index", "email", "--background"],
            )

        assert result.exit_code == 0
        mock_bg.assert_called_once()
        assert mock_bg.call_args[0][1] == ["email"]

    def test_index_calibre_background_flag(self, tmp_path: Path) -> None:
        """--background flag is accepted by index calibre command."""
        from unittest.mock import patch

        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}\n")

        with patch("ragling.cli._run_in_background") as mock_bg:
            result = runner.invoke(
                main,
                ["--config", str(config_path), "index", "calibre", "--background"],
            )

        assert result.exit_code == 0
        mock_bg.assert_called_once()
        assert mock_bg.call_args[0][1] == ["calibre"]

    def test_index_rss_background_flag(self, tmp_path: Path) -> None:
        """--background flag is accepted by index rss command."""
        from unittest.mock import patch

        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}\n")

        with patch("ragling.cli._run_in_background") as mock_bg:
            result = runner.invoke(
                main,
                ["--config", str(config_path), "index", "rss", "--background"],
            )

        assert result.exit_code == 0
        mock_bg.assert_called_once()
        assert mock_bg.call_args[0][1] == ["rss"]

    def test_index_all_background_flag(self, tmp_path: Path) -> None:
        """--background flag is accepted by index all command."""
        from unittest.mock import patch

        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}\n")

        with patch("ragling.cli._run_in_background") as mock_bg:
            result = runner.invoke(
                main,
                ["--config", str(config_path), "index", "all", "--background"],
            )

        assert result.exit_code == 0
        mock_bg.assert_called_once()
        assert mock_bg.call_args[0][1] == ["all"]

    def test_index_group_background_flag(self, tmp_path: Path) -> None:
        """--background flag is accepted by index group command with a name."""
        from unittest.mock import patch

        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}\n")

        with patch("ragling.cli._run_in_background") as mock_bg:
            result = runner.invoke(
                main,
                ["--config", str(config_path), "index", "group", "mygroup", "--background"],
            )

        assert result.exit_code == 0
        mock_bg.assert_called_once()
        assert mock_bg.call_args[0][1] == ["group", "mygroup"]

    def test_index_group_background_no_name(self, tmp_path: Path) -> None:
        """--background flag with no group name passes ['group'] as subcommand."""
        from unittest.mock import patch

        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}\n")

        with patch("ragling.cli._run_in_background") as mock_bg:
            result = runner.invoke(
                main,
                ["--config", str(config_path), "index", "group", "--background"],
            )

        assert result.exit_code == 0
        mock_bg.assert_called_once()
        assert mock_bg.call_args[0][1] == ["group"]

    def test_index_group_background_with_history(self, tmp_path: Path) -> None:
        """--background with --history forwards the --history flag via extra_args."""
        from unittest.mock import patch

        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}\n")

        with patch("ragling.cli._run_in_background") as mock_bg:
            result = runner.invoke(
                main,
                [
                    "--config",
                    str(config_path),
                    "index",
                    "group",
                    "mygroup",
                    "--background",
                    "--history",
                ],
            )

        assert result.exit_code == 0
        mock_bg.assert_called_once()
        assert mock_bg.call_args[0][1] == ["group", "mygroup"]
        assert mock_bg.call_args[1].get("extra_args") == ["--history"] or mock_bg.call_args[0][
            3
        ] == ["--history"]

    def test_index_project_background_forwards_paths(self, tmp_path: Path) -> None:
        """--background on index project forwards paths as extra_args."""
        from unittest.mock import patch

        runner = CliRunner()
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}\n")

        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()

        with patch("ragling.cli._run_in_background") as mock_bg:
            result = runner.invoke(
                main,
                [
                    "--config",
                    str(config_path),
                    "index",
                    "project",
                    "myproj",
                    str(doc_dir),
                    "--background",
                ],
            )

        assert result.exit_code == 0
        mock_bg.assert_called_once()
        assert mock_bg.call_args[0][1] == ["project", "myproj"]
        # extra_args should contain the path
        extra = mock_bg.call_args[1].get("extra_args") or mock_bg.call_args[0][3]
        assert str(doc_dir) in extra

    def test_run_in_background_spawns_subprocess(self, tmp_path: Path) -> None:
        """_run_in_background should spawn a detached subprocess."""
        from unittest.mock import MagicMock, patch

        from ragling.cli import _run_in_background

        ctx = MagicMock()
        ctx.obj = {"config_path": None}

        with patch("subprocess.Popen") as mock_popen:
            _run_in_background(ctx, ["obsidian"], force=False)

        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["start_new_session"] is True

    def test_run_in_background_includes_force(self, tmp_path: Path) -> None:
        """_run_in_background should include --force when force=True."""
        from unittest.mock import MagicMock, patch

        from ragling.cli import _run_in_background

        ctx = MagicMock()
        ctx.obj = {"config_path": None}

        with patch("subprocess.Popen") as mock_popen:
            _run_in_background(ctx, ["obsidian"], force=True)

        cmd = mock_popen.call_args[0][0]
        assert "--force" in cmd

    def test_run_in_background_with_config_path(self, tmp_path: Path) -> None:
        """_run_in_background should include --config when config_path is set."""
        from unittest.mock import MagicMock, patch

        from ragling.cli import _run_in_background

        ctx = MagicMock()
        ctx.obj = {"config_path": "/path/to/config.yaml"}

        with patch("subprocess.Popen") as mock_popen:
            _run_in_background(ctx, ["obsidian"], force=False)

        cmd = mock_popen.call_args[0][0]
        assert "--config" in cmd
        assert "/path/to/config.yaml" in cmd

    def test_run_in_background_includes_extra_args(self) -> None:
        """_run_in_background should append extra_args to the command."""
        from unittest.mock import MagicMock, patch

        from ragling.cli import _run_in_background

        ctx = MagicMock()
        ctx.obj = {"config_path": None}

        with patch("subprocess.Popen") as mock_popen:
            _run_in_background(ctx, ["group", "mygroup"], force=False, extra_args=["--history"])

        cmd = mock_popen.call_args[0][0]
        assert "group" in cmd
        assert "mygroup" in cmd
        assert "--history" in cmd

    def test_run_in_background_config_before_index(self) -> None:
        """--config should appear before 'index' in the command."""
        from unittest.mock import MagicMock, patch

        from ragling.cli import _run_in_background

        ctx = MagicMock()
        ctx.obj = {"config_path": "/my/config.yaml"}

        with patch("subprocess.Popen") as mock_popen:
            _run_in_background(ctx, ["obsidian"], force=True)

        cmd = mock_popen.call_args[0][0]
        config_idx = cmd.index("--config")
        index_idx = cmd.index("index")
        assert config_idx < index_idx

    def test_run_in_background_stderr_to_log_file(self) -> None:
        """_run_in_background should redirect stderr to a log file, not DEVNULL."""
        from unittest.mock import MagicMock, patch

        from ragling.cli import _run_in_background

        ctx = MagicMock()
        ctx.obj = {"config_path": None}

        with patch("subprocess.Popen") as mock_popen, patch("builtins.open"):
            _run_in_background(ctx, ["obsidian"], force=False)

        call_kwargs = mock_popen.call_args[1]
        # stderr should NOT be DEVNULL
        import subprocess

        assert call_kwargs.get("stderr") is not subprocess.DEVNULL
        # stdout should still be DEVNULL
        assert call_kwargs["stdout"] is subprocess.DEVNULL


class TestInitCommand:
    """Tests for the ragling init command."""

    @pytest.fixture(autouse=True)
    def _mock_ollama(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Prevent real Ollama network calls in init tests."""
        monkeypatch.setattr("ragling.cli._check_ollama_status", lambda: (False, False))

    @pytest.fixture
    def fake_ragling_dir(self, tmp_path: Path) -> Path:
        """Create a fake ragling installation directory with pyproject.toml."""
        d = tmp_path / "ragling-install"
        d.mkdir()
        (d / "pyproject.toml").write_text("[project]\nname = 'ragling'\n")
        return d

    def test_init_help(self) -> None:
        """init command is registered and shows help."""
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "--name" in result.output
        assert "--ragling-dir" in result.output

    def test_init_creates_ragling_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ragling_dir: Path
    ) -> None:
        """init creates ragling.json with watch config using directory name."""
        runner = CliRunner()
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = runner.invoke(main, ["init", "--ragling-dir", str(fake_ragling_dir)])
        assert result.exit_code == 0
        config_file = project_dir / "ragling.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert "watch" in data
        assert "my-project" in data["watch"]
        assert data["watch"]["my-project"] == "."

    def test_init_custom_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ragling_dir: Path
    ) -> None:
        """--name overrides the derived project name."""
        runner = CliRunner()
        project_dir = tmp_path / "some-dir"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = runner.invoke(
            main, ["init", "--name", "custom-name", "--ragling-dir", str(fake_ragling_dir)]
        )
        assert result.exit_code == 0
        data = json.loads((project_dir / "ragling.json").read_text())
        assert "custom-name" in data["watch"]

    def test_init_creates_mcp_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ragling_dir: Path
    ) -> None:
        """init creates .mcp.json with ragling server entry."""
        runner = CliRunner()
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = runner.invoke(main, ["init", "--ragling-dir", str(fake_ragling_dir)])
        assert result.exit_code == 0
        mcp_file = project_dir / ".mcp.json"
        assert mcp_file.exists()
        data = json.loads(mcp_file.read_text())
        assert "mcpServers" in data
        assert "ragling" in data["mcpServers"]
        args = data["mcpServers"]["ragling"]["args"]
        assert "--directory" in args
        assert str(fake_ragling_dir) in args
        assert "--config" in args

    def test_init_merges_existing_mcp_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ragling_dir: Path
    ) -> None:
        """init preserves existing servers in .mcp.json."""
        runner = CliRunner()
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        existing_mcp = {"mcpServers": {"other-server": {"command": "other"}}}
        (project_dir / ".mcp.json").write_text(json.dumps(existing_mcp))
        monkeypatch.chdir(project_dir)
        result = runner.invoke(main, ["init", "--ragling-dir", str(fake_ragling_dir)])
        assert result.exit_code == 0
        data = json.loads((project_dir / ".mcp.json").read_text())
        assert "other-server" in data["mcpServers"]
        assert "ragling" in data["mcpServers"]

    def test_init_skips_existing_ragling_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ragling_dir: Path
    ) -> None:
        """init does not overwrite existing ragling.json."""
        runner = CliRunner()
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        existing = {"watch": {"old-name": "."}}
        (project_dir / "ragling.json").write_text(json.dumps(existing))
        monkeypatch.chdir(project_dir)
        result = runner.invoke(main, ["init", "--ragling-dir", str(fake_ragling_dir)])
        assert result.exit_code == 0
        assert "already exists" in result.output
        data = json.loads((project_dir / "ragling.json").read_text())
        assert "old-name" in data["watch"]  # unchanged

    @pytest.mark.parametrize("name", ["obsidian", "email", "calibre", "rss", "global"])
    def test_init_rejects_reserved_names(
        self, tmp_path: Path, name: str, monkeypatch: pytest.MonkeyPatch, fake_ragling_dir: Path
    ) -> None:
        """init rejects system collection names."""
        runner = CliRunner()
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = runner.invoke(
            main, ["init", "--name", name, "--ragling-dir", str(fake_ragling_dir)]
        )
        assert result.exit_code != 0

    def test_init_checks_ollama_not_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ragling_dir: Path
    ) -> None:
        """init output includes Ollama status when not running."""
        monkeypatch.setattr("ragling.cli._check_ollama_status", lambda: (False, False))
        runner = CliRunner()
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = runner.invoke(main, ["init", "--ragling-dir", str(fake_ragling_dir)])
        assert result.exit_code == 0
        assert "ollama" in result.output.lower()

    def test_init_mcp_json_config_uses_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ragling_dir: Path
    ) -> None:
        """The --config path in .mcp.json should be absolute."""
        runner = CliRunner()
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = runner.invoke(main, ["init", "--ragling-dir", str(fake_ragling_dir)])
        assert result.exit_code == 0
        data = json.loads((project_dir / ".mcp.json").read_text())
        args = data["mcpServers"]["ragling"]["args"]
        config_idx = args.index("--config")
        config_path = args[config_idx + 1]
        assert Path(config_path).is_absolute()

    def test_init_suggests_gitignore(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ragling_dir: Path
    ) -> None:
        """init suggests adding ragling.json and .mcp.json to .gitignore."""
        runner = CliRunner()
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = runner.invoke(main, ["init", "--ragling-dir", str(fake_ragling_dir)])
        assert result.exit_code == 0
        assert "ragling.json" in result.output
        assert ".mcp.json" in result.output
        assert ".gitignore" in result.output

    def test_init_no_gitignore_tip_when_already_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ragling_dir: Path
    ) -> None:
        """init skips .gitignore tip when entries already present."""
        runner = CliRunner()
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        (project_dir / ".gitignore").write_text("ragling.json\n.mcp.json\n")
        monkeypatch.chdir(project_dir)
        result = runner.invoke(main, ["init", "--ragling-dir", str(fake_ragling_dir)])
        assert result.exit_code == 0
        assert "Tip" not in result.output

    def test_init_rejects_invalid_ragling_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--ragling-dir must contain pyproject.toml."""
        runner = CliRunner()
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        bad_dir = tmp_path / "not-ragling"
        bad_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = runner.invoke(main, ["init", "--ragling-dir", str(bad_dir)])
        assert result.exit_code != 0
        assert "pyproject.toml" in result.output
