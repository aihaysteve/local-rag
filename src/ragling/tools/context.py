"""ToolContext dataclass replacing closure captures in create_server."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ragling.config import Config, load_config

if TYPE_CHECKING:
    from ragling.indexing_queue import IndexingQueue
    from ragling.indexing_status import IndexingStatus


@dataclass
class ToolContext:
    """Shared state for all tool functions, replacing closure captures."""

    group_name: str
    server_config: Config | None
    indexing_status: IndexingStatus | None
    config_getter: Callable[[], Config] | None
    queue_getter: Callable[[], IndexingQueue | None] | None
    role_getter: Callable[[], str] | None

    def get_config(self) -> Config:
        """Return an effective Config with the correct group_name."""
        if self.config_getter:
            return self.config_getter().with_overrides(group_name=self.group_name)
        return (self.server_config or load_config()).with_overrides(group_name=self.group_name)

    def get_queue(self) -> IndexingQueue | None:
        """Resolve the current indexing queue."""
        if self.queue_getter is not None:
            return self.queue_getter()
        return None
