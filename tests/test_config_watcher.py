"""Tests for ragling.config_watcher module."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from ragling.config import Config


class TestConfigWatcher:
    """Tests for ConfigWatcher that monitors config.json for changes."""

    def test_initial_config_is_stored(self, tmp_path: Path) -> None:
        """ConfigWatcher stores the initial config."""
        from ragling.config_watcher import ConfigWatcher

        config = Config(home=tmp_path)
        watcher = ConfigWatcher(config, config_path=tmp_path / "config.json")
        assert watcher.get_config() is config

    def test_reload_updates_config(self, tmp_path: Path) -> None:
        """Reloading after config file change produces a new Config."""
        from ragling.config_watcher import ConfigWatcher

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = Config()
        watcher = ConfigWatcher(config, config_path=config_path)

        # Write new config
        config_path.write_text(json.dumps({"embedding_model": "mxbai-embed-large"}))

        # Trigger reload
        watcher.reload()

        new_config = watcher.get_config()
        assert new_config is not config
        assert new_config.embedding_model == "mxbai-embed-large"

    def test_reload_on_notify(self, tmp_path: Path) -> None:
        """notify_change triggers debounced reload."""
        from ragling.config_watcher import ConfigWatcher

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = Config()
        watcher = ConfigWatcher(config, config_path=config_path, debounce_seconds=0.1)

        config_path.write_text(json.dumps({"embedding_model": "new-model"}))
        watcher.notify_change()
        time.sleep(0.3)

        assert watcher.get_config().embedding_model == "new-model"

    def test_debounces_rapid_changes(self, tmp_path: Path) -> None:
        """Multiple rapid config changes result in one reload."""
        from ragling.config_watcher import ConfigWatcher

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"embedding_model": "model-1"}))

        config = Config()
        reload_count = MagicMock()
        watcher = ConfigWatcher(
            config,
            config_path=config_path,
            debounce_seconds=0.2,
            on_reload=reload_count,
        )

        config_path.write_text(json.dumps({"embedding_model": "model-2"}))
        watcher.notify_change()
        time.sleep(0.05)
        config_path.write_text(json.dumps({"embedding_model": "model-3"}))
        watcher.notify_change()
        time.sleep(0.05)
        config_path.write_text(json.dumps({"embedding_model": "model-4"}))
        watcher.notify_change()
        time.sleep(0.4)

        # Only one reload should have fired
        reload_count.assert_called_once()
        assert watcher.get_config().embedding_model == "model-4"

    def test_callback_receives_new_config(self, tmp_path: Path) -> None:
        """on_reload callback is called with the new Config."""
        from ragling.config_watcher import ConfigWatcher

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = Config()
        callback = MagicMock()
        watcher = ConfigWatcher(
            config,
            config_path=config_path,
            debounce_seconds=0.1,
            on_reload=callback,
        )

        config_path.write_text(json.dumps({"embedding_model": "new-model"}))
        watcher.notify_change()
        time.sleep(0.3)

        callback.assert_called_once()
        new_config = callback.call_args[0][0]
        assert isinstance(new_config, Config)
        assert new_config.embedding_model == "new-model"

    def test_reload_preserves_old_config_on_parse_error(self, tmp_path: Path) -> None:
        """If new config is invalid JSON, old config is preserved."""
        from ragling.config_watcher import ConfigWatcher

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = Config(embedding_model="bge-m3")
        watcher = ConfigWatcher(config, config_path=config_path, debounce_seconds=0.1)

        # Write invalid JSON
        config_path.write_text("not valid json{{{")
        watcher.notify_change()
        time.sleep(0.3)

        # Config should be unchanged
        assert watcher.get_config().embedding_model == "bge-m3"

    def test_get_config_is_thread_safe(self, tmp_path: Path) -> None:
        """get_config can be called from any thread safely."""
        import threading

        from ragling.config_watcher import ConfigWatcher

        config = Config()
        watcher = ConfigWatcher(config, config_path=tmp_path / "config.json")

        results = []

        def read_config() -> None:
            results.append(watcher.get_config())

        threads = [threading.Thread(target=read_config) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(c is config for c in results)

    def test_stop_cancels_pending_timer(self, tmp_path: Path) -> None:
        """Stopping the watcher cancels pending debounce timers."""
        from ragling.config_watcher import ConfigWatcher

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = Config()
        callback = MagicMock()
        watcher = ConfigWatcher(
            config,
            config_path=config_path,
            debounce_seconds=5.0,
            on_reload=callback,
        )

        watcher.notify_change()
        watcher.stop()
        time.sleep(0.2)

        # Timer was cancelled, callback should not have fired
        callback.assert_not_called()


class TestConfigReloadIntegration:
    """Tests for config reload triggering downstream actions."""

    def test_adding_vault_triggers_on_reload_callback(self, tmp_path: Path) -> None:
        """When config changes to add an obsidian vault, on_reload callback fires."""
        from ragling.config_watcher import ConfigWatcher

        config_path = tmp_path / "config.json"
        # Initial config with no obsidian vaults
        config_path.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = Config()
        callback = MagicMock()
        watcher = ConfigWatcher(
            config,
            config_path=config_path,
            on_reload=callback,
        )

        # Modify config to add an obsidian vault
        vault_path = str(tmp_path / "my-vault")
        config_path.write_text(
            json.dumps(
                {
                    "embedding_model": "bge-m3",
                    "obsidian_vaults": [vault_path],
                }
            )
        )

        # Trigger reload directly (no debounce needed)
        watcher.reload()

        # Assert callback was called with the new Config
        callback.assert_called_once()
        new_config = callback.call_args[0][0]
        assert isinstance(new_config, Config)
        assert len(new_config.obsidian_vaults) == 1
        assert str(new_config.obsidian_vaults[0]) == vault_path

    def test_disabling_collection_propagates_via_callback(self, tmp_path: Path) -> None:
        """Config change adding disabled_collections propagates via on_reload."""
        from ragling.config_watcher import ConfigWatcher

        config_path = tmp_path / "config.json"
        # Initial config with no disabled collections
        config_path.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = Config()
        callback = MagicMock()
        watcher = ConfigWatcher(
            config,
            config_path=config_path,
            on_reload=callback,
        )

        # Verify initial state: rss is enabled
        assert config.is_collection_enabled("rss") is True

        # Modify config to disable the rss collection
        config_path.write_text(
            json.dumps(
                {
                    "embedding_model": "bge-m3",
                    "disabled_collections": ["rss"],
                }
            )
        )

        # Trigger reload
        watcher.reload()

        # Assert callback was called with Config where rss is disabled
        callback.assert_called_once()
        new_config = callback.call_args[0][0]
        assert isinstance(new_config, Config)
        assert new_config.is_collection_enabled("rss") is False
        # Other collections should still be enabled
        assert new_config.is_collection_enabled("obsidian") is True
        assert new_config.is_collection_enabled("email") is True

    # -------------------------------------------------------------------
    # P2 #13 (S14.6): Config reload -> indexing_queue.set_config() integration
    # -------------------------------------------------------------------

    def test_on_reload_callback_can_wire_to_indexing_queue(self, tmp_path: Path) -> None:
        """The on_reload callback pattern works for wiring config changes to IndexingQueue."""
        from ragling.config_watcher import ConfigWatcher

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = Config()

        # Simulate an IndexingQueue with a set_config method
        mock_queue = MagicMock()

        watcher = ConfigWatcher(
            config,
            config_path=config_path,
            on_reload=mock_queue.set_config,
        )

        # Write updated config and trigger reload
        config_path.write_text(json.dumps({"embedding_model": "new-model"}))
        watcher.reload()

        # Assert set_config was called with the new Config
        mock_queue.set_config.assert_called_once()
        new_config = mock_queue.set_config.call_args[0][0]
        assert isinstance(new_config, Config)
        assert new_config.embedding_model == "new-model"


# ---------------------------------------------------------------------------
# P2 #16 (S15.7): Multi-threaded concurrent notify_change for ConfigWatcher
# ---------------------------------------------------------------------------


class TestConcurrentConfigNotifyChange:
    def test_concurrent_notify_change_is_thread_safe(self, tmp_path: Path) -> None:
        """Multiple threads calling notify_change simultaneously are handled safely."""
        from ragling.config_watcher import ConfigWatcher

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = Config()
        callback = MagicMock()
        watcher = ConfigWatcher(
            config,
            config_path=config_path,
            debounce_seconds=0.2,
            on_reload=callback,
        )

        # Write the final config value before the concurrent notifications
        config_path.write_text(json.dumps({"embedding_model": "concurrent-model"}))

        num_threads = 10
        barrier = threading.Barrier(num_threads)
        exceptions: list[Exception] = []

        def call_notify() -> None:
            try:
                barrier.wait()
                watcher.notify_change()
            except Exception as exc:
                exceptions.append(exc)

        threads = [threading.Thread(target=call_notify) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Wait for debounce to fire
        time.sleep(0.5)

        # No exceptions should have occurred in any thread
        assert exceptions == []
        # Debounce should coalesce all notifications into exactly one reload
        callback.assert_called_once()
        # The reloaded config should reflect the file contents
        assert watcher.get_config().embedding_model == "concurrent-model"
