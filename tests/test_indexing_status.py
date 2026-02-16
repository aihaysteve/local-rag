"""Tests for ragling.indexing_status module."""


class TestIndexingStatus:
    def test_initial_state_is_idle(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        assert status.is_active() is False
        assert status.to_dict() is None

    def test_set_remaining_makes_active(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.set_remaining(42)
        assert status.is_active() is True
        assert status.to_dict() == {"active": True, "remaining": 42}

    def test_decrement(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.set_remaining(3)
        status.decrement()
        assert status.to_dict() == {"active": True, "remaining": 2}

    def test_decrement_to_zero_becomes_idle(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.set_remaining(1)
        status.decrement()
        assert status.is_active() is False
        assert status.to_dict() is None

    def test_finish_resets_to_idle(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.set_remaining(10)
        status.finish()
        assert status.is_active() is False

    def test_thread_safety(self) -> None:
        """Multiple threads can safely update the counter."""
        import threading

        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.set_remaining(1000)

        def decrement_100() -> None:
            for _ in range(100):
                status.decrement()

        threads = [threading.Thread(target=decrement_100) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert status.to_dict() is None  # 1000 - (10 * 100) = 0
