"""File system, system database, and config file watching.

Re-exports for external consumers.  Internal code imports from submodules
directly (e.g. ``from ragling.watchers.watcher import ...``) so that test
``patch()`` targets resolve to the defining module.
"""

from ragling.watchers.config_watcher import ConfigWatcher
from ragling.watchers.system_watcher import SystemCollectionWatcher, start_system_watcher
from ragling.watchers.watcher import get_watch_paths, start_watcher

__all__ = [
    "ConfigWatcher",
    "SystemCollectionWatcher",
    "get_watch_paths",
    "start_system_watcher",
    "start_watcher",
]
