"""Tests for rag_index watch collection discovery routing."""

from pathlib import Path
from types import MappingProxyType
from unittest.mock import MagicMock

from ragling.config import Config


def _make_ctx(config: Config, queue: MagicMock) -> MagicMock:
    """Create a minimal ToolContext mock."""
    ctx = MagicMock()
    ctx.get_config.return_value = config
    ctx.get_queue.return_value = queue
    ctx.server_config = None
    ctx.indexing_status = None
    ctx.queue_getter = lambda: queue
    return ctx


class TestRagIndexWatchDiscovery:
    """Tests for rag_index routing watch collections through discovery."""

    def test_watch_with_nested_vault_submits_obsidian_job(self, tmp_path: Path) -> None:
        from ragling.tools.index import _rag_index_via_queue

        watch_dir = tmp_path / "workspace"
        watch_dir.mkdir()
        (watch_dir / ".git").mkdir()
        vault = watch_dir / "notes"
        vault.mkdir()
        (vault / ".obsidian").mkdir()

        config = Config(watch=MappingProxyType({"my-ws": (watch_dir,)}))
        queue = MagicMock()
        ctx = _make_ctx(config, queue)

        result = _rag_index_via_queue("my-ws", None, config, queue, ctx)

        assert result["status"] == "submitted"
        jobs = [call[0][0] for call in queue.submit.call_args_list]
        obsidian_jobs = [j for j in jobs if j.indexer_type == "obsidian"]
        assert len(obsidian_jobs) >= 1
        assert obsidian_jobs[0].collection_name == "obsidian"

    def test_watch_no_markers_submits_project_job(self, tmp_path: Path) -> None:
        from ragling.tools.index import _rag_index_via_queue

        watch_dir = tmp_path / "docs"
        watch_dir.mkdir()
        (watch_dir / "readme.md").write_text("# Hello")

        config = Config(watch=MappingProxyType({"docs": (watch_dir,)}))
        queue = MagicMock()
        ctx = _make_ctx(config, queue)

        result = _rag_index_via_queue("docs", None, config, queue, ctx)

        assert result["status"] == "submitted"
        jobs = [call[0][0] for call in queue.submit.call_args_list]
        assert len(jobs) == 1
        assert jobs[0].indexer_type == "project"
