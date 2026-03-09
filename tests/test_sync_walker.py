"""Tests for sync.py integration with the unified walker."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestSyncDirectorySource:
    """Tests that _sync_directory_source uses the unified walker."""

    @patch("ragling.indexers.walk_processor.process_walk_result")
    @patch("ragling.indexers.walker.walk")
    def test_calls_walk_and_process(
        self,
        mock_walk: MagicMock,
        mock_process: MagicMock,
        tmp_path: Path,
    ) -> None:
        """_sync_directory_source should call walk() then process_walk_result()."""
        from ragling.indexers.base import IndexResult
        from ragling.sync import _sync_directory_source

        mock_walk.return_value = MagicMock()
        mock_process.return_value = IndexResult(indexed=5)

        config = MagicMock()
        conn = MagicMock()

        result = _sync_directory_source(
            conn=conn,
            config=config,
            watch_name="test",
            watch_path=tmp_path,
        )

        mock_walk.assert_called_once()
        mock_process.assert_called_once()
        assert result.indexed == 5

    @patch("ragling.indexers.walk_processor.process_walk_result")
    @patch("ragling.indexers.walker.walk")
    def test_passes_exclusion_config(
        self,
        mock_walk: MagicMock,
        mock_process: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Should pass ExclusionConfig with global ragignore path."""
        from ragling.indexers.base import IndexResult
        from ragling.sync import _sync_directory_source

        mock_walk.return_value = MagicMock()
        mock_process.return_value = IndexResult()

        _sync_directory_source(
            conn=MagicMock(), config=MagicMock(), watch_name="test", watch_path=tmp_path
        )

        call_kwargs = mock_walk.call_args
        assert call_kwargs is not None
        assert "exclusion_config" in call_kwargs.kwargs

    @patch("ragling.indexers.walk_processor.process_walk_result")
    @patch("ragling.indexers.walker.walk")
    def test_passes_force_flag(
        self,
        mock_walk: MagicMock,
        mock_process: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Should pass force flag through to process_walk_result."""
        from ragling.indexers.base import IndexResult
        from ragling.sync import _sync_directory_source

        mock_walk.return_value = MagicMock()
        mock_process.return_value = IndexResult()

        _sync_directory_source(
            conn=MagicMock(),
            config=MagicMock(),
            watch_name="test",
            watch_path=tmp_path,
            force=True,
        )

        call_kwargs = mock_process.call_args
        assert call_kwargs is not None
        assert call_kwargs.kwargs.get("force") is True

    @patch("ragling.indexers.walk_processor.process_walk_result")
    @patch("ragling.indexers.walker.walk")
    def test_passes_watch_name_and_root(
        self,
        mock_walk: MagicMock,
        mock_process: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Should pass watch_name and watch_root to process_walk_result."""
        from ragling.indexers.base import IndexResult
        from ragling.sync import _sync_directory_source

        mock_walk.return_value = MagicMock()
        mock_process.return_value = IndexResult()

        _sync_directory_source(
            conn=MagicMock(),
            config=MagicMock(),
            watch_name="mywatch",
            watch_path=tmp_path,
        )

        call_kwargs = mock_process.call_args
        assert call_kwargs is not None
        assert call_kwargs.kwargs.get("watch_name") == "mywatch"
        assert call_kwargs.kwargs.get("watch_root") == tmp_path
