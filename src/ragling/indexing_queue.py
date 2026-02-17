"""Indexing queue with single worker thread.

All indexing operations (startup sync, file watcher, MCP tools) submit
IndexJob items to the queue. A single dedicated worker thread processes
them sequentially, ensuring thread safety by design — only the worker
thread writes to the database.

DocStore thread safety: Since only the worker thread calls indexers
(which in turn call DocStore.get_or_convert), the DocStore is
inherently safe without additional locking.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ragling.config import Config
from ragling.db import get_connection, get_or_create_collection, init_db
from ragling.indexing_status import IndexingStatus

if TYPE_CHECKING:
    from ragling.doc_store import DocStore
    from ragling.indexers.base import IndexResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexJob:
    """A unit of indexing work to be processed by the worker thread.

    Attributes:
        job_type: Kind of job — "directory", "file", "file_deleted",
            or "system_collection".
        path: File or directory path. None for system collections that
            don't have a single path (e.g. email, calibre).
        collection_name: Target collection name.
        indexer_type: Which indexer to use — "obsidian", "code", "project",
            "email", "calibre", "rss", or "prune".
        force: If True, re-index even if content hasn't changed.
    """

    job_type: str
    path: Path | None
    collection_name: str
    indexer_type: str
    force: bool = False


@dataclass
class IndexRequest:
    """Wrapper for synchronous job submission with completion signaling.

    Wraps an IndexJob with a threading.Event for blocking until the
    worker completes processing, and a result slot for the IndexResult.
    """

    job: IndexJob
    done: threading.Event = field(default_factory=threading.Event)
    result: IndexResult | None = None


class IndexingQueue:
    """Thread-safe indexing queue with a single worker thread.

    Submitters call :meth:`submit` from any thread. The worker thread
    picks up jobs sequentially and routes them to the correct indexer
    via :meth:`_process`.

    Args:
        config: Application configuration.
        status: Indexing status tracker for progress reporting.
    """

    def __init__(self, config: Config, status: IndexingStatus) -> None:
        self._queue: queue.Queue[IndexJob | None] = queue.Queue()
        self._config = config
        self._status = status
        self._worker = threading.Thread(target=self._run, name="index-worker", daemon=True)

    def start(self) -> None:
        """Start the worker thread."""
        self._worker.start()

    def submit(self, job: IndexJob) -> None:
        """Add a job to the queue.

        Increments the indexing status counter immediately.

        Args:
            job: The indexing job to enqueue.
        """
        self._queue.put(job)
        self._status.increment(job.collection_name)

    def shutdown(self) -> None:
        """Signal the worker to stop and wait for it to finish."""
        self._queue.put(None)  # sentinel
        self._worker.join(timeout=30)
        if self._worker.is_alive():
            logger.warning("Index worker did not shut down within 30s")

    def _run(self) -> None:
        """Worker loop: process jobs until sentinel (None) is received."""
        while True:
            job = self._queue.get()
            if job is None:
                break
            try:
                self._process(job)
            except Exception:
                logger.exception("Indexing failed: %s", job)
            finally:
                self._status.decrement(job.collection_name)

    def _process(self, job: IndexJob) -> None:
        """Route a job to the correct indexer.

        This is the single place where indexer routing lives.

        Args:
            job: The indexing job to process.

        Raises:
            ValueError: If the indexer_type is not recognized.
        """
        if job.indexer_type == "project":
            self._index_project(job)
        elif job.indexer_type == "code":
            self._index_code(job)
        elif job.indexer_type == "obsidian":
            self._index_obsidian(job)
        elif job.indexer_type == "email":
            self._index_email(job)
        elif job.indexer_type == "calibre":
            self._index_calibre(job)
        elif job.indexer_type == "rss":
            self._index_rss(job)
        elif job.indexer_type == "prune":
            self._prune(job)
        else:
            raise ValueError(f"Unknown indexer_type: {job.indexer_type!r}")

    @contextmanager
    def _open_conn(self) -> Iterator[sqlite3.Connection]:
        """Open an initialized DB connection, closing it on exit."""
        conn = get_connection(self._config)
        init_db(conn, self._config)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _open_conn_and_docstore(self) -> Iterator[tuple[sqlite3.Connection, DocStore]]:
        """Open a DB connection and DocStore, closing both on exit."""
        from ragling.doc_store import DocStore

        with self._open_conn() as conn:
            doc_store = DocStore(self._config.shared_db_path)
            try:
                yield conn, doc_store
            finally:
                doc_store.close()

    @staticmethod
    def _require_path(job: IndexJob) -> Path:
        """Extract and validate that job.path is not None."""
        if job.path is None:
            raise ValueError(f"{job.indexer_type} job requires a path")
        return job.path

    def _index_project(self, job: IndexJob) -> None:
        from ragling.indexers.project import ProjectIndexer

        with self._open_conn_and_docstore() as (conn, doc_store):
            paths = [job.path] if job.path else []
            indexer = ProjectIndexer(job.collection_name, paths, doc_store=doc_store)
            result = indexer.index(conn, self._config, force=job.force)
            logger.info("Indexed project %s: %s", job.collection_name, result)

    def _index_code(self, job: IndexJob) -> None:
        from ragling.indexers.git_indexer import GitRepoIndexer

        path = self._require_path(job)
        with self._open_conn() as conn:
            indexer = GitRepoIndexer(path, collection_name=job.collection_name)
            result = indexer.index(conn, self._config, force=job.force, index_history=True)
            logger.info("Indexed code %s: %s", job.collection_name, result)

    def _index_obsidian(self, job: IndexJob) -> None:
        from ragling.indexers.obsidian import ObsidianIndexer

        with self._open_conn_and_docstore() as (conn, doc_store):
            vault_paths = [job.path] if job.path else self._config.obsidian_vaults
            indexer = ObsidianIndexer(
                vault_paths, self._config.obsidian_exclude_folders, doc_store=doc_store
            )
            result = indexer.index(conn, self._config, force=job.force)
            logger.info("Indexed obsidian: %s", result)

    def _index_email(self, job: IndexJob) -> None:
        from ragling.indexers.email_indexer import EmailIndexer

        with self._open_conn() as conn:
            db_path = str(job.path) if job.path else str(self._config.emclient_db_path)
            indexer = EmailIndexer(db_path)
            result = indexer.index(conn, self._config, force=job.force)
            logger.info("Indexed email: %s", result)

    def _index_calibre(self, job: IndexJob) -> None:
        from ragling.indexers.calibre_indexer import CalibreIndexer

        with self._open_conn_and_docstore() as (conn, doc_store):
            libraries = [job.path] if job.path else self._config.calibre_libraries
            indexer = CalibreIndexer(libraries, doc_store=doc_store)
            result = indexer.index(conn, self._config, force=job.force)
            logger.info("Indexed calibre: %s", result)

    def _index_rss(self, job: IndexJob) -> None:
        from ragling.indexers.rss_indexer import RSSIndexer

        with self._open_conn() as conn:
            db_path = str(job.path) if job.path else str(self._config.netnewswire_db_path)
            indexer = RSSIndexer(db_path)
            result = indexer.index(conn, self._config, force=job.force)
            logger.info("Indexed rss: %s", result)

    def _prune(self, job: IndexJob) -> None:
        from ragling.indexers.base import delete_source

        path = self._require_path(job)
        with self._open_conn() as conn:
            collection_id = get_or_create_collection(conn, job.collection_name, "project")
            delete_source(conn, collection_id, str(path.resolve()))
            logger.info("Pruned source: %s from %s", path, job.collection_name)
