"""Server startup orchestration.

Encapsulates the serve command's complex startup sequence: leader
election, IndexingQueue management, config watching, watcher startup,
and shutdown. Extracted from cli.py to make the orchestration testable
and reusable outside the CLI.
"""

from __future__ import annotations

import atexit
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import click

from ragling.config import DEFAULT_CONFIG_PATH, Config
from ragling.indexing_status import IndexingStatus

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.indexing_queue import IndexingQueue
    from ragling.leader import LeaderLock
    from ragling.watchers.config_watcher import ConfigWatcher

logger = logging.getLogger(__name__)


class ServerOrchestrator:
    """Orchestrates the MCP server startup sequence.

    Manages leader election, IndexingQueue creation, config watching,
    file/system watcher startup, and clean shutdown. Converts the nested
    closures from cli.py::serve() into methods with shared mutable state
    as instance attributes.

    Args:
        config: Initial application configuration.
        group: Group name for per-group indexes.
        config_path: Path to the config file. Defaults to
            ``~/.ragling/config.json``.
    """

    def __init__(
        self,
        config: Config,
        group: str,
        config_path: Path | None = None,
    ) -> None:
        self._config = config
        self._group = group
        self._config_path = config_path

        self.indexing_status = IndexingStatus()
        self._current_queue: IndexingQueue | None = None
        self._lock: LeaderLock | None = None
        self._config_watcher: ConfigWatcher | None = None
        self._shutdown_registered = False

    def queue_getter(self) -> IndexingQueue | None:
        """Return the current IndexingQueue, or None if not yet created."""
        return self._current_queue

    def handle_config_reload(self, new_config: Config) -> None:
        """Handle a config file reload by propagating to the queue.

        Args:
            new_config: The newly loaded Config instance.
        """
        q = self._current_queue
        if q is not None:
            q.set_config(new_config)
        logger.info("Config reloaded")

    def _require_config_watcher(self) -> ConfigWatcher:
        """Return _config_watcher or raise if run() hasn't been called."""
        if self._config_watcher is None:
            raise RuntimeError("ServerOrchestrator.run() must be called before this method")
        return self._config_watcher

    def start_leader_infrastructure(self) -> None:
        """Start IndexingQueue, sync, and watchers (leader startup sequence)."""
        import threading

        from ragling.indexing_queue import IndexingQueue
        from ragling.sync import run_startup_sync, submit_file_change
        from ragling.watchers.watcher import get_watch_paths, start_watcher

        config_watcher = self._require_config_watcher()
        current_config = config_watcher.get_config()
        queue = IndexingQueue(current_config, self.indexing_status)
        queue.start()
        self._current_queue = queue

        sync_done = threading.Event()
        run_startup_sync(current_config, queue, done_event=sync_done)

        if get_watch_paths(current_config):

            def _on_files_changed(files: list[Path]) -> None:
                logger.info("File changes detected: %d files", len(files))
                for file_path in files:
                    submit_file_change(file_path, config_watcher.get_config(), queue)

            def _start_watcher_after_sync() -> None:
                sync_done.wait()
                try:
                    observer = start_watcher(config_watcher.get_config(), _on_files_changed)
                    if observer is not None:
                        logger.info("File watcher started successfully")
                    else:
                        logger.warning("File watcher returned None (no directories to watch)")
                except Exception:
                    logger.exception("Failed to start file watcher")

            threading.Thread(
                target=_start_watcher_after_sync, name="watcher-wait", daemon=True
            ).start()

        def _start_system_watcher_after_sync() -> None:
            sync_done.wait()
            try:
                from ragling.watchers.system_watcher import start_system_watcher

                start_system_watcher(config_watcher.get_config(), queue)
                logger.info("System collection watcher started")
            except Exception:
                logger.exception("Failed to start system collection watcher")

        threading.Thread(
            target=_start_system_watcher_after_sync,
            name="sys-watcher-wait",
            daemon=True,
        ).start()

    def shutdown(self) -> None:
        """Clean up resources: stop queue, release lock, stop config watcher."""
        logger.info("Shutting down...")
        if self._lock is not None:
            self._lock.close()
        q = self._current_queue
        if q is not None:
            q.shutdown()
        if self._config_watcher is not None:
            self._config_watcher.stop()

    def create_mcp_server(self) -> FastMCP:
        """Create and return a configured FastMCP server instance."""
        from ragling.mcp_server import create_server

        config_watcher = self._require_config_watcher()
        if self._lock is None:
            raise RuntimeError("ServerOrchestrator.run() must be called before this method")

        lock = self._lock  # capture for lambda closure (mypy narrowing)

        return create_server(
            group_name=self._group,
            config=self._config,
            indexing_status=self.indexing_status,
            config_getter=config_watcher.get_config,
            queue_getter=self.queue_getter,
            role_getter=lambda: "leader" if lock.is_leader else "follower",
        )

    def run(self, *, sse: bool, no_stdio: bool, port: int) -> None:
        """Run the full server startup sequence.

        Sets up config watching, leader election, atexit handler, and
        starts the MCP server with the requested transport(s).

        Args:
            sse: Whether to enable SSE transport.
            no_stdio: Whether to disable stdio transport.
            port: Port for SSE transport.
        """
        from ragling.leader import LeaderLock, lock_path_for_config
        from ragling.watchers.config_watcher import ConfigWatcher

        # Config watching (both leader and follower need fresh config)
        self._config_watcher = ConfigWatcher(
            self._config,
            config_path=self._config_path if self._config_path else DEFAULT_CONFIG_PATH,
            on_reload=self.handle_config_reload,
        )

        # Leader election
        leader_config = self._config.with_overrides(group_name=self._group)
        self._lock = LeaderLock(lock_path_for_config(leader_config))

        if self._lock.try_acquire():
            logger.info("Starting as leader for group '%s'", self._group)
            self.start_leader_infrastructure()
        else:
            logger.info("Starting as follower for group '%s' (search-only)", self._group)
            self._lock.start_retry(
                interval=30.0,
                on_promote=self.start_leader_infrastructure,
            )

        if not self._shutdown_registered:
            atexit.register(self.shutdown)
            self._shutdown_registered = True

        server = self.create_mcp_server()

        if sse:
            import anyio

            import uvicorn

            from ragling.auth.tls import ensure_tls_certs

            tls_config = ensure_tls_certs()
            server.settings.port = port
            starlette_app = server.sse_app()

            uv_config = uvicorn.Config(
                starlette_app,
                host=server.settings.host,
                port=port,
                log_level=server.settings.log_level.lower(),
                ssl_certfile=str(tls_config.server_cert),
                ssl_keyfile=str(tls_config.server_key),
            )
            uv_server = uvicorn.Server(uv_config)

            if not no_stdio:
                click.echo(
                    f"Starting MCP server (stdio + HTTPS/SSE on port {port}, "
                    f"group: {self._group})..."
                )

                async def _run_both() -> None:
                    async with anyio.create_task_group() as tg:
                        tg.start_soon(uv_server.serve)
                        tg.start_soon(server.run_stdio_async)

                anyio.run(_run_both)
            else:
                click.echo(
                    f"Starting MCP server on port {port} (HTTPS/SSE only, group: {self._group})..."
                )
                anyio.run(uv_server.serve)
        elif not no_stdio:
            server.run(transport="stdio")
