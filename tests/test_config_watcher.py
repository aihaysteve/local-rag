"""Tests for ragling.config_watcher module."""

import json
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
