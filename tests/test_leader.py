"""Tests for ragling.leader module."""

from pathlib import Path

from ragling.config import Config


class TestLockPathForConfig:
    """Tests for deriving lock file path from config."""

    def test_default_group_uses_db_path(self, tmp_path: Path) -> None:
        from ragling.leader import lock_path_for_config

        config = Config(db_path=tmp_path / "rag.db", group_name="default")
        result = lock_path_for_config(config)
        assert result == tmp_path / "rag.db.lock"

    def test_named_group_uses_group_index_path(self, tmp_path: Path) -> None:
        from ragling.leader import lock_path_for_config

        config = Config(
            group_db_dir=tmp_path / "groups",
            group_name="personal",
        )
        result = lock_path_for_config(config)
        assert result == tmp_path / "groups" / "personal" / "index.db.lock"


class TestLeaderLock:
    """Tests for LeaderLock acquire, contention, and release."""

    def test_acquire_succeeds_on_fresh_file(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock = LeaderLock(tmp_path / "test.lock")
        assert lock.try_acquire() is True
        assert lock.is_leader is True
        lock.close()

    def test_acquire_creates_parent_directory(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock_path = tmp_path / "nested" / "dir" / "test.lock"
        lock = LeaderLock(lock_path)
        assert lock.try_acquire() is True
        assert lock_path.exists()
        lock.close()

    def test_second_lock_on_same_path_fails(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock_path = tmp_path / "test.lock"
        lock1 = LeaderLock(lock_path)
        lock2 = LeaderLock(lock_path)

        assert lock1.try_acquire() is True
        assert lock2.try_acquire() is False
        assert lock2.is_leader is False

        lock1.close()
        lock2.close()

    def test_release_allows_reacquisition(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock_path = tmp_path / "test.lock"
        lock1 = LeaderLock(lock_path)
        lock2 = LeaderLock(lock_path)

        assert lock1.try_acquire() is True
        lock1.close()

        assert lock2.try_acquire() is True
        assert lock2.is_leader is True
        lock2.close()

    def test_context_manager_acquires_and_releases(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock_path = tmp_path / "test.lock"
        with LeaderLock(lock_path) as lock:
            assert lock.try_acquire() is True
            assert lock.is_leader is True

        # After context exit, another lock should succeed
        lock2 = LeaderLock(lock_path)
        assert lock2.try_acquire() is True
        lock2.close()

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock = LeaderLock(tmp_path / "test.lock")
        lock.try_acquire()
        lock.close()
        lock.close()  # Should not raise

    def test_is_leader_false_before_acquire(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock = LeaderLock(tmp_path / "test.lock")
        assert lock.is_leader is False
        lock.close()
