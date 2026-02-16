"""Tests for ragling.db module."""

from pathlib import Path

from ragling.config import Config


class TestGetConnection:
    """Tests for get_connection with per-group path selection."""

    def test_uses_group_index_db_path_when_group_set(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            group_name="test-group",
            group_db_dir=tmp_path / "groups",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            expected_path = tmp_path / "groups" / "test-group" / "index.db"
            assert expected_path.exists()
        finally:
            conn.close()

    def test_falls_back_to_db_path_for_default_group(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            db_path=tmp_path / "legacy.db",
            group_name="default",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            assert (tmp_path / "legacy.db").exists()
        finally:
            conn.close()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            group_name="deep-group",
            group_db_dir=tmp_path / "a" / "b" / "c",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            expected = tmp_path / "a" / "b" / "c" / "deep-group" / "index.db"
            assert expected.exists()
        finally:
            conn.close()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            group_name="wal-test",
            group_db_dir=tmp_path / "groups",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"
        finally:
            conn.close()
