"""Config file watcher with debounced reload.

Monitors the config file for changes and atomically replaces the
Config reference when the file is modified. The new Config is a
frozen dataclass — no mutation, just replacement.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from ragling.config import Config, DEFAULT_CONFIG_PATH, load_config

logger = logging.getLogger(__name__)

_DEFAULT_DEBOUNCE_SECONDS = 2.0


class ConfigWatcher:
    """Watches a config file and reloads on change.

    Thread-safe: ``get_config()`` can be called from any thread.
    The internal Config reference is atomically replaced on reload.

    Args:
        initial_config: The starting Config instance.
        config_path: Path to the config file to watch.
        debounce_seconds: Seconds to wait after last change before reloading.
        on_reload: Optional callback invoked with the new Config after reload.
    """

    def __init__(
        self,
        initial_config: Config,
        config_path: Path = DEFAULT_CONFIG_PATH,
        debounce_seconds: float = _DEFAULT_DEBOUNCE_SECONDS,
        on_reload: Callable[[Config], None] | None = None,
    ) -> None:
        self._config = initial_config
        self._config_path = config_path
        self._debounce = debounce_seconds
        self._on_reload = on_reload
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def get_config(self) -> Config:
        """Return the current Config instance.

        Thread-safe — reads are atomic on CPython due to the GIL,
        but we use a lock for correctness on all platforms.
        """
        with self._lock:
            return self._config

    def reload(self) -> None:
        """Reload config from disk and replace the current instance.

        If the file is invalid or unreadable, the current config is preserved.
        """
        try:
            new_config = load_config(self._config_path)
        except Exception:
            logger.exception("Failed to reload config from %s", self._config_path)
            return

        with self._lock:
            self._config = new_config

        logger.info("Config reloaded from %s", self._config_path)

        if self._on_reload:
            try:
                self._on_reload(new_config)
            except Exception:
                logger.exception("Error in config reload callback")

    def notify_change(self) -> None:
        """Notify that the config file has changed.

        Resets the debounce timer. After the debounce period, triggers a reload.
        """
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce, self._debounced_reload)
            self._timer.daemon = True
            self._timer.start()

    def stop(self) -> None:
        """Cancel any pending reload timer."""
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def _debounced_reload(self) -> None:
        """Called by the timer after debounce period expires."""
        with self._lock:
            self._timer = None
        self.reload()
