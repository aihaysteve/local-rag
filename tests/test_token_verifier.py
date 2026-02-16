"""Tests for the ragling token verifier."""

import asyncio

from ragling.config import Config, UserConfig


class TestRaglingTokenVerifier:
    """Tests for API key verification."""

    def _run(self, coro):
        """Helper to run async functions in tests."""
        return asyncio.run(coro)

    def test_valid_key_returns_access_token(self):
        config = Config(
            users={"kitchen": UserConfig(api_key="rag_kitchen_key")},
        )
        from ragling.token_verifier import RaglingTokenVerifier

        verifier = RaglingTokenVerifier(config)
        result = self._run(verifier.verify_token("rag_kitchen_key"))
        assert result is not None
        assert result.client_id == "kitchen"
        assert result.token == "rag_kitchen_key"

    def test_invalid_key_returns_none(self):
        config = Config(
            users={"kitchen": UserConfig(api_key="rag_kitchen_key")},
        )
        from ragling.token_verifier import RaglingTokenVerifier

        verifier = RaglingTokenVerifier(config)
        result = self._run(verifier.verify_token("wrong_key"))
        assert result is None

    def test_no_users_returns_none(self):
        config = Config()
        from ragling.token_verifier import RaglingTokenVerifier

        verifier = RaglingTokenVerifier(config)
        result = self._run(verifier.verify_token("any_key"))
        assert result is None

    def test_empty_token_returns_none(self):
        config = Config(
            users={"kitchen": UserConfig(api_key="rag_kitchen_key")},
        )
        from ragling.token_verifier import RaglingTokenVerifier

        verifier = RaglingTokenVerifier(config)
        result = self._run(verifier.verify_token(""))
        assert result is None
