"""Tests for ragling.indexing_status module."""


class TestIndexingStatus:
    def test_initial_state_is_idle(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        assert status.is_active() is False
        assert status.to_dict() is None

    def test_increment_with_collection_makes_active(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("obsidian")
        assert status.is_active() is True

    def test_increment_default_count(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("email")
        result = status.to_dict()
        assert result is not None
        assert result["total_remaining"] == 1
        assert result["collections"] == {"email": 1}

    def test_increment_with_count(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("obsidian", 5)
        result = status.to_dict()
        assert result is not None
        assert result["total_remaining"] == 5
        assert result["collections"] == {"obsidian": 5}

    def test_increment_multiple_collections(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("obsidian", 3)
        status.increment("email", 2)
        result = status.to_dict()
        assert result is not None
        assert result["total_remaining"] == 5
        assert result["collections"] == {"obsidian": 3, "email": 2}
        assert result["active"] is True

    def test_decrement_reduces_count(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("obsidian", 3)
        status.decrement("obsidian")
        result = status.to_dict()
        assert result is not None
        assert result["collections"] == {"obsidian": 2}

    def test_decrement_to_zero_removes_collection(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("email")
        status.decrement("email")
        assert status.is_active() is False
        assert status.to_dict() is None

    def test_decrement_one_collection_leaves_others(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("obsidian", 2)
        status.increment("email", 1)
        status.decrement("email")
        result = status.to_dict()
        assert result is not None
        assert result["collections"] == {"obsidian": 2}
        assert result["total_remaining"] == 2

    def test_decrement_below_zero_clamps(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.decrement("obsidian")
        assert status.is_active() is False
        assert status.to_dict() is None

    def test_finish_resets_all_collections(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("obsidian", 10)
        status.increment("email", 5)
        status.finish()
        assert status.is_active() is False
        assert status.to_dict() is None

    def test_to_dict_returns_none_when_idle(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        assert status.to_dict() is None

    def test_thread_safety(self) -> None:
        """Multiple threads can safely update per-collection counters."""
        import threading

        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("obsidian", 500)
        status.increment("email", 500)

        def decrement_obsidian_100() -> None:
            for _ in range(100):
                status.decrement("obsidian")

        def decrement_email_100() -> None:
            for _ in range(100):
                status.decrement("email")

        threads = [threading.Thread(target=decrement_obsidian_100) for _ in range(5)]
        threads += [threading.Thread(target=decrement_email_100) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert status.to_dict() is None  # 500 - 500 = 0 each


class TestFileLevelStatus:
    """Tests for file-level indexing progress."""

    def test_set_file_total_and_processed(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.set_file_total("obsidian", 100)
        status.file_processed("obsidian", 55)

        result = status.to_dict()
        assert result is not None
        assert result["collections"]["obsidian"]["total"] == 100
        assert result["collections"]["obsidian"]["processed"] == 55
        assert result["collections"]["obsidian"]["remaining"] == 45
        assert result["total_remaining"] == 45

    def test_file_counts_replace_job_counts_when_present(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.increment("obsidian")  # job-level: 1 remaining
        status.set_file_total("obsidian", 50)  # file-level: 50 remaining

        result = status.to_dict()
        assert result is not None
        # File-level should take precedence
        assert result["total_remaining"] == 50

    def test_mixed_file_and_job_level_total_remaining(self) -> None:
        """total_remaining aggregates across file-level and job-level collections."""
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        # Add job-level counts for email
        status.increment("email", 2)
        # Add file-level counts for obsidian
        status.set_file_total("obsidian", 100)
        status.file_processed("obsidian", 60)

        result = status.to_dict()
        assert result is not None
        # total_remaining = 2 (email job-level) + 40 (obsidian: 100-60) = 42
        assert result["total_remaining"] == 42
        # email should be a plain integer (job-level)
        assert result["collections"]["email"] == 2
        # obsidian should be a dict with file-level shape
        assert isinstance(result["collections"]["obsidian"], dict)
        assert result["collections"]["obsidian"]["total"] == 100
        assert result["collections"]["obsidian"]["processed"] == 60
        assert result["collections"]["obsidian"]["remaining"] == 40

    def test_to_dict_shape(self) -> None:
        from ragling.indexing_status import IndexingStatus

        status = IndexingStatus()
        status.set_file_total("email", 30)
        status.file_processed("email", 30)
        status.set_file_total("obsidian", 100)
        status.file_processed("obsidian", 55)

        result = status.to_dict()
        assert result is not None
        assert result["active"] is True
        assert "collections" in result
        assert result["collections"]["obsidian"]["remaining"] == 45
        assert result["collections"]["email"]["remaining"] == 0
