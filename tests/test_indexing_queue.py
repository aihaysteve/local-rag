"""Tests for ragling.indexing_queue module."""

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ragling.config import Config
from ragling.indexing_queue import IndexJob, IndexingQueue, IndexRequest
from ragling.indexing_status import IndexingStatus


class TestIndexJob:
    def test_frozen(self) -> None:
        job = IndexJob(
            job_type="directory",
            path=Path("/test"),
            collection_name="test-coll",
            indexer_type="project",
        )
        with pytest.raises(AttributeError):
            job.path = Path("/other")  # type: ignore[misc]

    def test_defaults(self) -> None:
        job = IndexJob(
            job_type="file",
            path=Path("/test.md"),
            collection_name="docs",
            indexer_type="project",
        )
        assert job.force is False

    def test_force_flag(self) -> None:
        job = IndexJob(
            job_type="file",
            path=Path("/test.md"),
            collection_name="docs",
            indexer_type="project",
            force=True,
        )
        assert job.force is True

    def test_path_can_be_none(self) -> None:
        job = IndexJob(
            job_type="system_collection",
            path=None,
            collection_name="email",
            indexer_type="email",
        )
        assert job.path is None


class TestIndexingQueue:
    def _make_queue(
        self, config: Config | None = None, status: IndexingStatus | None = None
    ) -> IndexingQueue:
        cfg = config or Config(embedding_dimensions=4)
        st = status or IndexingStatus()
        return IndexingQueue(cfg, st)

    def test_submit_increments_status(self) -> None:
        status = IndexingStatus()
        q = self._make_queue(status=status)
        job = IndexJob(
            job_type="file",
            path=Path("/test.md"),
            collection_name="docs",
            indexer_type="project",
        )
        q.submit(job)
        assert status.is_active() is True
        assert status.to_dict() == {
            "active": True,
            "total_remaining": 1,
            "collections": {"docs": 1},
        }

    def test_worker_processes_jobs(self) -> None:
        """Worker thread picks up and processes submitted jobs."""
        status = IndexingStatus()
        q = self._make_queue(status=status)

        processed: list[IndexJob] = []

        with patch.object(q, "_process", side_effect=lambda job: processed.append(job)):
            q.start()
            job = IndexJob(
                job_type="file",
                path=Path("/test.md"),
                collection_name="docs",
                indexer_type="project",
            )
            q.submit(job)
            q.shutdown()

        assert len(processed) == 1
        assert processed[0] is job

    def test_worker_decrements_status_after_processing(self) -> None:
        status = IndexingStatus()
        q = self._make_queue(status=status)

        with patch.object(q, "_process"):
            q.start()
            q.submit(
                IndexJob(
                    job_type="file",
                    path=Path("/a.md"),
                    collection_name="docs",
                    indexer_type="project",
                )
            )
            q.shutdown()

        assert status.is_active() is False

    def test_worker_handles_exceptions(self) -> None:
        """Worker should continue after an error in _process."""
        status = IndexingStatus()
        q = self._make_queue(status=status)
        call_count = 0

        def failing_then_ok(job: IndexJob) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")

        with patch.object(q, "_process", side_effect=failing_then_ok):
            q.start()
            q.submit(
                IndexJob(
                    job_type="file",
                    path=Path("/fail.md"),
                    collection_name="docs",
                    indexer_type="project",
                )
            )
            q.submit(
                IndexJob(
                    job_type="file",
                    path=Path("/ok.md"),
                    collection_name="docs",
                    indexer_type="project",
                )
            )
            q.shutdown()

        assert call_count == 2
        assert status.is_active() is False

    def test_shutdown_sends_sentinel(self) -> None:
        """Shutdown should cause worker thread to exit."""
        q = self._make_queue()
        q.start()
        q.shutdown()
        assert not q._worker.is_alive()

    def test_multiple_jobs_processed_in_order(self) -> None:
        status = IndexingStatus()
        q = self._make_queue(status=status)
        order: list[str] = []

        def track_order(job: IndexJob) -> None:
            order.append(str(job.path))

        with patch.object(q, "_process", side_effect=track_order):
            q.start()
            for i in range(5):
                q.submit(
                    IndexJob(
                        job_type="file",
                        path=Path(f"/file{i}.md"),
                        collection_name="docs",
                        indexer_type="project",
                    )
                )
            q.shutdown()

        assert order == [f"/file{i}.md" for i in range(5)]


class TestProcessRouter:
    """Test that _process routes to the correct indexer."""

    def _make_queue_and_process(self, job: IndexJob) -> None:
        """Create a queue and call _process directly (no threading)."""
        config = Config(
            embedding_dimensions=4,
            shared_db_path=Path("/tmp/test_shared.db"),
        )
        status = IndexingStatus()
        q = IndexingQueue(config, status)
        q._process(job)

    @patch("ragling.doc_store.DocStore")
    @patch("ragling.indexing_queue.init_db")
    @patch("ragling.indexing_queue.get_connection")
    @patch("ragling.indexers.project.ProjectIndexer")
    def test_routes_project(
        self, mock_proj: MagicMock, mock_conn: MagicMock, mock_init: MagicMock, mock_ds: MagicMock
    ) -> None:
        mock_conn.return_value = MagicMock()
        mock_ds.return_value = MagicMock()
        mock_proj.return_value.index.return_value = MagicMock()

        job = IndexJob(
            job_type="directory",
            path=Path("/docs"),
            collection_name="my-project",
            indexer_type="project",
        )
        self._make_queue_and_process(job)
        mock_proj.assert_called_once()

    @patch("ragling.indexing_queue.init_db")
    @patch("ragling.indexing_queue.get_connection")
    @patch("ragling.indexers.git_indexer.GitRepoIndexer")
    def test_routes_code(
        self, mock_git: MagicMock, mock_conn: MagicMock, mock_init: MagicMock
    ) -> None:
        mock_conn.return_value = MagicMock()
        mock_git.return_value.index.return_value = MagicMock()

        job = IndexJob(
            job_type="directory",
            path=Path("/repo"),
            collection_name="my-org",
            indexer_type="code",
        )
        self._make_queue_and_process(job)
        mock_git.assert_called_once()

    @patch("ragling.doc_store.DocStore")
    @patch("ragling.indexing_queue.init_db")
    @patch("ragling.indexing_queue.get_connection")
    @patch("ragling.indexers.obsidian.ObsidianIndexer")
    def test_routes_obsidian(
        self, mock_obs: MagicMock, mock_conn: MagicMock, mock_init: MagicMock, mock_ds: MagicMock
    ) -> None:
        mock_conn.return_value = MagicMock()
        mock_ds.return_value = MagicMock()
        mock_obs.return_value.index.return_value = MagicMock()

        job = IndexJob(
            job_type="directory",
            path=Path("/vault"),
            collection_name="obsidian",
            indexer_type="obsidian",
        )
        self._make_queue_and_process(job)
        mock_obs.assert_called_once()

    @patch("ragling.indexing_queue.init_db")
    @patch("ragling.indexing_queue.get_connection")
    @patch("ragling.indexers.email_indexer.EmailIndexer")
    def test_routes_email(
        self, mock_email: MagicMock, mock_conn: MagicMock, mock_init: MagicMock
    ) -> None:
        mock_conn.return_value = MagicMock()
        mock_email.return_value.index.return_value = MagicMock()

        job = IndexJob(
            job_type="system_collection",
            path=Path("/emclient"),
            collection_name="email",
            indexer_type="email",
        )
        self._make_queue_and_process(job)
        mock_email.assert_called_once()

    @patch("ragling.doc_store.DocStore")
    @patch("ragling.indexing_queue.init_db")
    @patch("ragling.indexing_queue.get_connection")
    @patch("ragling.indexers.calibre_indexer.CalibreIndexer")
    def test_routes_calibre(
        self, mock_cal: MagicMock, mock_conn: MagicMock, mock_init: MagicMock, mock_ds: MagicMock
    ) -> None:
        mock_conn.return_value = MagicMock()
        mock_ds.return_value = MagicMock()
        mock_cal.return_value.index.return_value = MagicMock()

        job = IndexJob(
            job_type="system_collection",
            path=None,
            collection_name="calibre",
            indexer_type="calibre",
        )
        self._make_queue_and_process(job)
        mock_cal.assert_called_once()

    @patch("ragling.indexing_queue.init_db")
    @patch("ragling.indexing_queue.get_connection")
    @patch("ragling.indexers.rss_indexer.RSSIndexer")
    def test_routes_rss(
        self, mock_rss: MagicMock, mock_conn: MagicMock, mock_init: MagicMock
    ) -> None:
        mock_conn.return_value = MagicMock()
        mock_rss.return_value.index.return_value = MagicMock()

        job = IndexJob(
            job_type="system_collection",
            path=Path("/nnw"),
            collection_name="rss",
            indexer_type="rss",
        )
        self._make_queue_and_process(job)
        mock_rss.assert_called_once()

    @patch("ragling.indexers.base.delete_source")
    @patch("ragling.indexing_queue.get_or_create_collection")
    @patch("ragling.indexing_queue.init_db")
    @patch("ragling.indexing_queue.get_connection")
    def test_routes_prune(
        self,
        mock_conn: MagicMock,
        mock_init: MagicMock,
        mock_get_coll: MagicMock,
        mock_delete: MagicMock,
    ) -> None:
        mock_conn.return_value = MagicMock()
        mock_get_coll.return_value = 42

        job = IndexJob(
            job_type="file_deleted",
            path=Path("/deleted.md"),
            collection_name="docs",
            indexer_type="prune",
        )
        self._make_queue_and_process(job)
        mock_delete.assert_called_once()

    def test_unknown_indexer_type_raises(self) -> None:
        job = IndexJob(
            job_type="file",
            path=Path("/test"),
            collection_name="docs",
            indexer_type="unknown_type",
        )
        with pytest.raises(ValueError, match="Unknown indexer_type"):
            self._make_queue_and_process(job)


class TestSubmitAndWait:
    """Tests for IndexingQueue.submit_and_wait()."""

    def test_blocks_until_job_completes(self, tmp_path: Path) -> None:
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        status = IndexingStatus()
        queue = IndexingQueue(config, status)
        queue.start()

        job = IndexJob(
            job_type="directory",
            path=tmp_path,
            collection_name="test-coll",
            indexer_type="project",
        )

        try:
            result = queue.submit_and_wait(job, timeout=30)
            assert result is not None
        finally:
            queue.shutdown()

    def test_timeout_returns_none(self, tmp_path: Path) -> None:
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        status = IndexingStatus()
        queue = IndexingQueue(config, status)
        queue.start()

        # Block the worker with a slow job so our second job times out
        slow_event = threading.Event()
        original_process = queue._process

        def _blocking_process(job: IndexJob) -> None:  # type: ignore[return]
            slow_event.wait(timeout=10)
            return original_process(job)

        queue._process = _blocking_process  # type: ignore[assignment]

        # Submit a blocker job first
        blocker = IndexJob(
            job_type="directory",
            path=tmp_path,
            collection_name="test-coll",
            indexer_type="project",
        )
        queue.submit(blocker)

        # Now submit our real job — it will queue behind the blocker
        job = IndexJob(
            job_type="directory",
            path=tmp_path,
            collection_name="test-coll",
            indexer_type="project",
        )

        result = queue.submit_and_wait(job, timeout=0.1)
        assert result is None

        # Unblock the worker and shut down cleanly
        slow_event.set()
        queue.shutdown()


class TestSetConfig:
    """Tests for IndexingQueue.set_config()."""

    def test_set_config_replaces_config(self, tmp_path: Path) -> None:
        from ragling.indexing_queue import IndexingQueue
        from ragling.indexing_status import IndexingStatus

        config1 = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )
        config2 = config1.with_overrides(embedding_dimensions=8)

        status = IndexingStatus()
        queue = IndexingQueue(config1, status)
        assert queue._config.embedding_dimensions == 4

        queue.set_config(config2)
        assert queue._config.embedding_dimensions == 8


class TestIndexRequest:
    """Tests for the IndexRequest synchronous wrapper."""

    def test_index_request_has_event_and_result(self) -> None:
        job = IndexJob(
            job_type="directory",
            path=Path("/tmp/test"),
            collection_name="test",
            indexer_type="project",
        )
        request = IndexRequest(job=job)
        assert not request.done.is_set()
        assert request.result is None
