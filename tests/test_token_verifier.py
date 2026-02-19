"""Tests for the ragling token verifier."""

import asyncio
from unittest.mock import patch

from ragling.config import Config, UserConfig
from ragling.token_verifier import RaglingTokenVerifier


def _hk(token: str) -> str:
    """Hash a token the same way the verifier does, for test assertions."""
    return RaglingTokenVerifier._hash_token(token)


class TestRaglingTokenVerifier:
    """Tests for API key verification."""

    def _run(self, coro):
        """Helper to run async functions in tests."""
        return asyncio.run(coro)

    def test_valid_key_returns_access_token(self):
        config = Config(
            users={"kitchen": UserConfig(api_key="rag_kitchen_key")},
        )
        verifier = RaglingTokenVerifier(config)
        result = self._run(verifier.verify_token("rag_kitchen_key"))
        assert result is not None
        assert result.client_id == "kitchen"
        assert result.token == "rag_kitchen_key"

    def test_invalid_key_returns_none(self):
        config = Config(
            users={"kitchen": UserConfig(api_key="rag_kitchen_key")},
        )
        verifier = RaglingTokenVerifier(config)
        result = self._run(verifier.verify_token("wrong_key"))
        assert result is None

    def test_no_users_returns_none(self):
        config = Config()
        verifier = RaglingTokenVerifier(config)
        result = self._run(verifier.verify_token("any_key"))
        assert result is None

    def test_empty_token_returns_none(self):
        config = Config(
            users={"kitchen": UserConfig(api_key="rag_kitchen_key")},
        )
        verifier = RaglingTokenVerifier(config)
        result = self._run(verifier.verify_token(""))
        assert result is None


class TestRateLimiting:
    """Tests for exponential backoff rate limiting on failed auth attempts."""

    def _run(self, coro):
        """Helper to run async functions in tests."""
        return asyncio.run(coro)

    def _make_verifier(self) -> RaglingTokenVerifier:
        config = Config(
            users={"kitchen": UserConfig(api_key="rag_kitchen_key")},
        )
        return RaglingTokenVerifier(config)

    def test_failures_below_threshold_are_not_rate_limited(self):
        """Fewer than MAX_FAILURES attempts should not trigger rate limiting."""
        verifier = self._make_verifier()
        # 5 failures should still allow attempts (threshold is >5)
        for _ in range(5):
            result = self._run(verifier.verify_token("bad_key"))
            assert result is None  # Normal auth failure, not rate-limited

    def test_rate_limiting_kicks_in_after_threshold_failures(self):
        """After exceeding MAX_FAILURES with the same token, verify_token
        should raise RateLimitedError instead of checking the credential."""
        verifier = self._make_verifier()
        from ragling.token_verifier import RateLimitedError

        # Exhaust the threshold (6 failures to exceed >5)
        for _ in range(6):
            self._run(verifier.verify_token("bad_key"))

        # Next attempt with the same token should be rate-limited
        import pytest

        with pytest.raises(RateLimitedError):
            self._run(verifier.verify_token("bad_key"))

    def test_backoff_time_increases_exponentially(self):
        """Each successive failure beyond the threshold should increase
        the backoff delay exponentially: 2^count seconds, capped at 300s."""
        verifier = self._make_verifier()

        fake_time = 1000.0

        with patch("ragling.token_verifier.time") as mock_time:
            mock_time.monotonic.return_value = fake_time

            # Accumulate 7 failures (count goes to 7)
            for _ in range(7):
                try:
                    self._run(verifier.verify_token("bad_key"))
                except Exception:
                    pass

            # Check the internal state: next_allowed should be
            # fake_time + min(2^7, 300) = 1000 + 128 = 1128
            key = _hk("bad_key")
            count, next_allowed = verifier._failures[key]
            assert count == 7
            assert next_allowed == fake_time + 2**7  # 128 seconds

    def test_backoff_capped_at_300_seconds(self):
        """Backoff should never exceed 300 seconds."""
        verifier = self._make_verifier()

        fake_time = 1000.0

        with patch("ragling.token_verifier.time") as mock_time:
            mock_time.monotonic.return_value = fake_time

            # Accumulate 20 failures (2^20 = 1_048_576 >> 300)
            for _ in range(20):
                try:
                    self._run(verifier.verify_token("bad_key"))
                except Exception:
                    pass

            count, next_allowed = verifier._failures[_hk("bad_key")]
            assert count == 20
            # Capped at 300s, not 2^20
            assert next_allowed == fake_time + 300

    def test_successful_auth_clears_failure_record(self):
        """A successful verification should remove the token's failure record."""
        verifier = self._make_verifier()

        # Accumulate some failures
        for _ in range(3):
            self._run(verifier.verify_token("rag_kitchen_key_wrong"))

        # Failures should be tracked
        assert _hk("rag_kitchen_key_wrong") in verifier._failures

        # Now try a token that previously had failures but not over threshold
        # Set up failures for the valid key, then succeed
        verifier._failures[_hk("rag_kitchen_key")] = (3, 0.0)

        result = self._run(verifier.verify_token("rag_kitchen_key"))
        assert result is not None
        assert result.client_id == "kitchen"
        # Failure record should be cleared after success
        assert _hk("rag_kitchen_key") not in verifier._failures

    def test_rate_limit_expires_after_backoff_period(self):
        """Once the backoff period passes, the token should be allowed again."""
        verifier = self._make_verifier()
        from ragling.token_verifier import RateLimitedError

        fake_time = 1000.0

        with patch("ragling.token_verifier.time") as mock_time:
            mock_time.monotonic.return_value = fake_time

            # Accumulate 6 failures to trigger rate limiting
            for _ in range(6):
                self._run(verifier.verify_token("bad_key"))

            # Should be rate-limited now (count=6 > 5)
            import pytest

            with pytest.raises(RateLimitedError):
                self._run(verifier.verify_token("bad_key"))

            # The rate-limited rejection incremented count to 7 and set
            # next_allowed = 1000 + 2^7 = 1128. Advance time past that.
            mock_time.monotonic.return_value = fake_time + 129.0

            # Should be allowed again (will fail auth, but not rate-limited)
            result = self._run(verifier.verify_token("bad_key"))
            assert result is None  # Auth failure, not rate limit

    def test_different_tokens_tracked_independently(self):
        """Rate limiting for one token should not affect another."""
        verifier = self._make_verifier()
        from ragling.token_verifier import RateLimitedError

        # Exhaust threshold for one token
        for _ in range(6):
            self._run(verifier.verify_token("bad_key_1"))

        # bad_key_1 should be rate-limited
        import pytest

        with pytest.raises(RateLimitedError):
            self._run(verifier.verify_token("bad_key_1"))

        # bad_key_2 should still work (auth failure, not rate-limited)
        result = self._run(verifier.verify_token("bad_key_2"))
        assert result is None

    def test_cleanup_removes_expired_entries(self):
        """Entries older than the cleanup threshold should be removed."""
        verifier = self._make_verifier()

        fake_time = 1000.0

        with patch("ragling.token_verifier.time") as mock_time:
            mock_time.monotonic.return_value = fake_time

            # Add some failures
            for _ in range(3):
                self._run(verifier.verify_token("old_key"))
                self._run(verifier.verify_token("new_key"))

            assert _hk("old_key") in verifier._failures
            assert _hk("new_key") in verifier._failures

            # Advance time past cleanup threshold (10 minutes = 600s)
            # Manually set old_key's next_allowed to be in the past
            verifier._failures[_hk("old_key")] = (3, fake_time - 1.0)
            # new_key's next_allowed is still in the future
            verifier._failures[_hk("new_key")] = (3, fake_time + 700.0)

            mock_time.monotonic.return_value = fake_time + 601.0

            verifier._cleanup_stale_entries()

            # old_key should be cleaned up (next_allowed is 601s in the past)
            assert _hk("old_key") not in verifier._failures
            # new_key should remain (next_allowed is still in the future)
            assert _hk("new_key") in verifier._failures

    def test_lazy_cleanup_triggered_periodically(self):
        """Cleanup should be triggered during verify_token calls
        when enough time has passed since last cleanup."""
        verifier = self._make_verifier()

        fake_time = 2000.0

        with patch("ragling.token_verifier.time") as mock_time:
            mock_time.monotonic.return_value = fake_time

            # Add a stale entry: next_allowed is 601+ seconds in the past
            verifier._failures[_hk("stale_key")] = (3, fake_time - 601.0)
            verifier._last_cleanup = fake_time - 601.0  # Force cleanup to trigger

            # This verify_token call should trigger lazy cleanup
            self._run(verifier.verify_token("some_token"))

            # Stale entry should have been cleaned up
            assert _hk("stale_key") not in verifier._failures
