"""Tests for server.py -- startup orchestration."""

from unittest.mock import MagicMock

import pytest

from ragling.config import Config


class TestServerOrchestratorImport:
    """ServerOrchestrator is importable."""

    def test_importable(self) -> None:
        from ragling.server import ServerOrchestrator

        assert ServerOrchestrator is not None


class TestServerOrchestratorInit:
    """ServerOrchestrator initializes with correct state."""

    def test_queue_starts_none(self) -> None:
        from ragling.server import ServerOrchestrator

        config = Config()
        orch = ServerOrchestrator(config, group="default")
        assert orch.queue_getter() is None

    def test_indexing_status_created(self) -> None:
        from ragling.server import ServerOrchestrator

        config = Config()
        orch = ServerOrchestrator(config, group="default")
        assert orch.indexing_status is not None


class TestConfigReload:
    """Config reload propagates to queue."""

    def test_reload_updates_queue_config(self) -> None:
        from ragling.server import ServerOrchestrator

        config = Config()
        orch = ServerOrchestrator(config, group="default")
        mock_queue = MagicMock()
        orch._current_queue = mock_queue

        new_config = Config()
        orch.handle_config_reload(new_config)
        mock_queue.set_config.assert_called_once_with(new_config)

    def test_reload_without_queue_does_not_error(self) -> None:
        from ragling.server import ServerOrchestrator

        config = Config()
        orch = ServerOrchestrator(config, group="default")
        orch._current_queue = None

        new_config = Config()
        orch.handle_config_reload(new_config)  # should not raise


class TestRunRequired:
    """Methods that need run() raise RuntimeError if called early."""

    def test_start_leader_before_run_raises(self) -> None:
        from ragling.server import ServerOrchestrator

        config = Config()
        orch = ServerOrchestrator(config, group="default")
        with pytest.raises(RuntimeError, match="run\\(\\) must be called"):
            orch.start_leader_infrastructure()

    def test_create_mcp_server_before_run_raises(self) -> None:
        from ragling.server import ServerOrchestrator

        config = Config()
        orch = ServerOrchestrator(config, group="default")
        with pytest.raises(RuntimeError, match="run\\(\\) must be called"):
            orch.create_mcp_server()


class TestShutdown:
    """Shutdown cleans up resources."""

    def test_shutdown_stops_queue(self) -> None:
        from ragling.server import ServerOrchestrator

        config = Config()
        orch = ServerOrchestrator(config, group="default")
        mock_queue = MagicMock()
        orch._current_queue = mock_queue
        mock_lock = MagicMock()
        orch._lock = mock_lock
        mock_watcher = MagicMock()
        orch._config_watcher = mock_watcher

        orch.shutdown()
        mock_queue.shutdown.assert_called_once()
        mock_lock.close.assert_called_once()
        mock_watcher.stop.assert_called_once()
