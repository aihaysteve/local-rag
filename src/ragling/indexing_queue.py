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
from ragling.indexer_types import IndexerType
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
    indexer_type: IndexerType
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
        self._queue: queue.Queue[IndexJob | IndexRequest | None] = queue.Queue()
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

    def submit_and_wait(self, job: IndexJob, timeout: float = 300) -> IndexResult | None:
        """Submit a job and block until it completes.

        Args:
            job: The indexing job to enqueue.
            timeout: Maximum seconds to wait for completion.

        Returns:
            The IndexResult, or None if the timeout expired or processing
            raised an exception.

        Note:
            On timeout the job remains in the queue and will still be
            processed by the worker; only the result is discarded. If the
            worker raises during processing, the done event is still set
            and this method returns None.
        """
        request = IndexRequest(job=job)
        self._queue.put(request)
        self._status.increment(job.collection_name)
        if request.done.wait(timeout=timeout):
            return request.result
        return None

    def set_config(self, config: Config) -> None:
        """Replace the current config.

        Safe under the GIL — attribute assignment is atomic. The worker
        thread reads _config at the start of each job.
        """
        self._config = config

    def shutdown(self) -> None:
        """Signal the worker to stop and wait for it to finish."""
        self._queue.put(None)
        self._worker.join(timeout=30)
        if self._worker.is_alive():
            logger.warning("Index worker did not shut down within 30 s")

    def _run(self) -> None:
        """Worker loop: process jobs until sentinel (None) is received."""
        while True:
            item = self._queue.get()
            if item is None:
                break

            if isinstance(item, IndexRequest):
                job = item.job
            else:
                job = item

            try:
                result = self._process(job)
                if isinstance(item, IndexRequest):
                    item.result = result
            except Exception:
                logger.exception("Indexing failed: %s", job)
                self._status.record_failure(job.collection_name, str(job))
            finally:
                self._status.decrement(job.collection_name)
                if isinstance(item, IndexRequest):
                    item.done.set()

    # Types that need a DocStore for Docling document conversion
    _DOCSTORE_TYPES = frozenset(
        {
            IndexerType.OBSIDIAN,
            IndexerType.CALIBRE,
            IndexerType.PROJECT,
            IndexerType.CODE,
        }
    )

    def _process(self, job: IndexJob) -> IndexResult | None:
        """Route a job to the correct indexer via the factory.

        Delegates indexer creation to ``indexers.factory.create_indexer()``.
        Prune jobs are handled separately since they don't use an indexer.

        Args:
            job: The indexing job to process.

        Returns:
            The IndexResult from the indexer, or None for prune jobs.

        Raises:
            ValueError: If the indexer_type is not recognized.
        """
        if job.indexer_type == IndexerType.PRUNE:
            self._prune(job)
            return None

        return self._index_via_factory(job)

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

    def _index_via_factory(self, job: IndexJob) -> IndexResult | None:
        """Create an indexer via the factory and run it.

        Handles DocStore lifecycle, index_history for code repos,
        and the document pass for code repos.
        """
        from ragling.indexers.factory import create_indexer

        needs_docstore = job.indexer_type in self._DOCSTORE_TYPES
        is_code = job.indexer_type == IndexerType.CODE

        if needs_docstore:
            with self._open_conn_and_docstore() as (conn, doc_store):
                indexer = create_indexer(
                    job.collection_name,
                    self._config,
                    path=job.path,
                    doc_store=doc_store,
                    indexer_type=job.indexer_type,
                )
                if is_code:
                    # GitRepoIndexer.index() accepts index_history; BaseIndexer does not
                    result = indexer.index(
                        conn,
                        self._config,
                        force=job.force,
                        status=self._status,
                        index_history=True,  # type: ignore[call-arg]
                    )
                    self._run_document_pass(conn, job, doc_store)
                else:
                    result = indexer.index(conn, self._config, force=job.force, status=self._status)
                logger.info("Indexed %s %s: %s", job.indexer_type, job.collection_name, result)
                return result
        else:
            with self._open_conn() as conn:
                indexer = create_indexer(
                    job.collection_name,
                    self._config,
                    path=job.path,
                    indexer_type=job.indexer_type,
                )
                result = indexer.index(conn, self._config, force=job.force, status=self._status)
                logger.info("Indexed %s %s: %s", job.indexer_type, job.collection_name, result)
                return result

    def _run_document_pass(
        self, conn: sqlite3.Connection, job: IndexJob, doc_store: DocStore
    ) -> None:
        """Run the document pass for code repos (non-code files like docx, pdf)."""
        from ragling.indexers.project import ProjectIndexer

        path = self._require_path(job)
        proj = ProjectIndexer(job.collection_name, [path], doc_store=doc_store)
        doc_result = proj._index_repo_documents(
            conn, self._config, path, job.collection_name, job.force
        )
        if doc_result.indexed > 0:
            logger.info("Document pass for %s: %d indexed", job.collection_name, doc_result.indexed)

    def _prune(self, job: IndexJob) -> None:
        from ragling.indexers.base import delete_source

        path = self._require_path(job)
        with self._open_conn() as conn:
            collection_id = get_or_create_collection(conn, job.collection_name, "project")
            delete_source(conn, collection_id, str(path.resolve()))
            logger.info("Pruned source: %s from %s", path, job.collection_name)
