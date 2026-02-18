"""Tests for ragling.leader module."""

import threading
import time
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


class TestLeaderLockRetry:
    """Tests for the periodic retry thread that promotes followers."""

    def test_retry_promotes_after_leader_releases(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock_path = tmp_path / "test.lock"
        leader = LeaderLock(lock_path)
        follower = LeaderLock(lock_path)

        assert leader.try_acquire() is True
        assert follower.try_acquire() is False

        promoted = threading.Event()
        follower.start_retry(interval=0.1, on_promote=promoted.set)

        # Release leader — follower should promote
        leader.close()
        assert promoted.wait(timeout=3.0), "Follower was not promoted"
        assert follower.is_leader is True

        follower.stop_retry()
        follower.close()

    def test_on_promote_callback_called(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock_path = tmp_path / "test.lock"
        leader = LeaderLock(lock_path)
        follower = LeaderLock(lock_path)

        assert leader.try_acquire() is True
        assert follower.try_acquire() is False

        callback_args: list[str] = []

        def on_promote() -> None:
            callback_args.append("promoted")

        follower.start_retry(interval=0.1, on_promote=on_promote)
        leader.close()
        time.sleep(0.5)

        assert callback_args == ["promoted"]

        follower.stop_retry()
        follower.close()

    def test_stop_retry_stops_thread(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock_path = tmp_path / "test.lock"
        leader = LeaderLock(lock_path)
        follower = LeaderLock(lock_path)

        assert leader.try_acquire() is True
        assert follower.try_acquire() is False

        follower.start_retry(interval=0.1)
        follower.stop_retry()

        assert not follower._retry_thread.is_alive()

        leader.close()
        follower.close()

    def test_retry_thread_is_daemon(self, tmp_path: Path) -> None:
        from ragling.leader import LeaderLock

        lock_path = tmp_path / "test.lock"
        leader = LeaderLock(lock_path)
        follower = LeaderLock(lock_path)

        assert leader.try_acquire() is True
        assert follower.try_acquire() is False

        follower.start_retry(interval=0.1)
        assert follower._retry_thread.daemon is True

        follower.stop_retry()
        leader.close()
        follower.close()

    def test_close_stops_retry(self, tmp_path: Path) -> None:
        """close() should also stop the retry thread."""
        from ragling.leader import LeaderLock

        lock_path = tmp_path / "test.lock"
        leader = LeaderLock(lock_path)
        follower = LeaderLock(lock_path)

        assert leader.try_acquire() is True
        assert follower.try_acquire() is False

        follower.start_retry(interval=0.1)
        retry_thread = follower._retry_thread
        follower.close()

        assert retry_thread is not None
        retry_thread.join(timeout=2.0)
        assert not retry_thread.is_alive()

        leader.close()
