"""Tests for ragling.embeddings module."""

from unittest.mock import MagicMock, patch

import pytest

from ragling.config import Config
from ragling.embeddings import (
    OllamaConnectionError,
    _client,
    _raise_if_connection_error,
    get_embedding,
    get_embeddings,
)


class TestClientHostConfig:
    """_client() passes ollama_host to ollama.Client when configured."""

    @patch("ragling.embeddings.ollama.Client")
    def test_no_host_when_ollama_host_is_none(self, mock_client_cls: MagicMock) -> None:
        config = Config()
        _client(config)
        call_kwargs = mock_client_cls.call_args[1]
        assert "host" not in call_kwargs

    @patch("ragling.embeddings.ollama.Client")
    def test_passes_host_when_ollama_host_set(self, mock_client_cls: MagicMock) -> None:
        config = Config(ollama_host="http://gpu-box:11434")
        _client(config)
        call_kwargs = mock_client_cls.call_args[1]
        assert call_kwargs["host"] == "http://gpu-box:11434"

    @patch("ragling.embeddings.ollama.Client")
    def test_always_passes_timeout(self, mock_client_cls: MagicMock) -> None:
        config = Config()
        _client(config)
        call_kwargs = mock_client_cls.call_args[1]
        assert "timeout" in call_kwargs


class TestHostAwareErrorMessages:
    """Error messages should include the configured host."""

    def test_default_message_suggests_ollama_serve(self) -> None:
        with pytest.raises(OllamaConnectionError, match="ollama serve"):
            _raise_if_connection_error(ConnectionError("connection refused"), config=Config())

    def test_remote_host_message_shows_url(self) -> None:
        config = Config(ollama_host="http://gpu-box:11434")
        with pytest.raises(OllamaConnectionError, match="gpu-box:11434"):
            _raise_if_connection_error(ConnectionError("connection refused"), config=config)

    def test_non_connection_error_is_ignored(self) -> None:
        _raise_if_connection_error(ValueError("something else"), config=Config())


class TestGetEmbeddingsBatchFallback:
    """get_embeddings() falls back to individual embedding on batch failure."""

    @patch("ragling.embeddings.ollama.Client")
    def test_successful_batch_unchanged(self, mock_client_cls: MagicMock) -> None:
        """Happy path: batch succeeds, returns embeddings directly."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.return_value = {"embeddings": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]}
        config = Config(embedding_dimensions=2)
        result = get_embeddings(["a", "b", "c"], config)
        assert result == [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
        assert mock_client.embed.call_count == 1

    @patch("ragling.embeddings.ollama.Client")
    def test_batch_failure_retries_individually(self, mock_client_cls: MagicMock) -> None:
        """Batch of 3 fails, individual calls succeed, returns 3 embeddings."""
        mock_client = mock_client_cls.return_value

        # First call (batch) fails, then 3 individual calls succeed
        mock_client.embed.side_effect = [
            RuntimeError("json: unsupported value: NaN"),
            {"embeddings": [[1.0, 2.0]]},
            {"embeddings": [[3.0, 4.0]]},
            {"embeddings": [[5.0, 6.0]]},
        ]
        config = Config(embedding_dimensions=2)
        result = get_embeddings(["a", "b", "c"], config)
        assert result == [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
        assert mock_client.embed.call_count == 4  # 1 batch + 3 individual

    @patch("ragling.embeddings.ollama.Client")
    def test_individual_failure_retries_with_truncated_text(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Batch fails, individual fails, truncated retry succeeds."""
        mock_client = mock_client_cls.return_value
        long_text = " ".join(["word"] * 300)  # 300 words, will be truncated to 256
        truncated = " ".join(["word"] * 256)

        # Batch fails, individual with full text fails, truncated retry succeeds
        mock_client.embed.side_effect = [
            RuntimeError("json: unsupported value: NaN"),
            RuntimeError("json: unsupported value: NaN"),
            {"embeddings": [[1.0, 2.0]]},
        ]
        config = Config(embedding_dimensions=2)
        result = get_embeddings([long_text], config)
        assert result == [[1.0, 2.0]]
        # 3 calls: batch, individual full text, individual truncated
        assert mock_client.embed.call_count == 3
        # The third call should use truncated text
        third_call_input = mock_client.embed.call_args_list[2][1]["input"]
        assert third_call_input == truncated

    @patch("ragling.embeddings.ollama.Client")
    def test_individual_failure_raises_when_truncated_retry_also_fails(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Batch fails, individual fails, truncated retry also fails → raises."""
        mock_client = mock_client_cls.return_value

        # Batch fails, individual fails, truncated retry also fails
        mock_client.embed.side_effect = [
            RuntimeError("json: unsupported value: NaN"),
            RuntimeError("first individual failure"),
            RuntimeError("truncated retry also failed"),
        ]
        config = Config(embedding_dimensions=2)
        with pytest.raises(RuntimeError, match="truncated retry also failed"):
            get_embeddings(["some text here"], config)

    @patch("ragling.embeddings.ollama.Client")
    def test_connection_error_in_batch_still_raises(self, mock_client_cls: MagicMock) -> None:
        """Batch fails with connection error → raises immediately, no retry."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.side_effect = ConnectionError("connection refused")

        config = Config(embedding_dimensions=2)
        with pytest.raises(OllamaConnectionError):
            get_embeddings(["a", "b", "c"], config)
        assert mock_client.embed.call_count == 1  # no individual retries

    @patch("ragling.embeddings.ollama.Client")
    def test_connection_error_in_individual_retry_still_raises(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Batch fails (non-connection), individual retry hits connection error."""
        mock_client = mock_client_cls.return_value

        # Batch fails with NaN error, first individual retry hits connection error
        mock_client.embed.side_effect = [
            RuntimeError("json: unsupported value: NaN"),
            ConnectionError("connection refused"),
        ]
        config = Config(embedding_dimensions=2)
        with pytest.raises(OllamaConnectionError):
            get_embeddings(["a", "b", "c"], config)


class TestGetEmbeddingTruncationRetry:
    """get_embedding() retries with truncated text on failure."""

    @patch("ragling.embeddings.ollama.Client")
    def test_successful_embedding_not_retried(self, mock_client_cls: MagicMock) -> None:
        """Successful embedding returns directly without retry."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.return_value = {"embeddings": [[1.0, 2.0]]}
        config = Config(embedding_dimensions=2)
        result = get_embedding("hello world", config)
        assert result == [1.0, 2.0]
        assert mock_client.embed.call_count == 1

    @patch("ragling.embeddings.ollama.Client")
    def test_failure_retries_with_truncated_text(self, mock_client_cls: MagicMock) -> None:
        """First call fails, retries with text truncated to 256 words."""
        mock_client = mock_client_cls.return_value
        long_text = " ".join(["word"] * 300)
        truncated = " ".join(["word"] * 256)

        mock_client.embed.side_effect = [
            RuntimeError("embedding failed"),
            {"embeddings": [[1.0, 2.0]]},
        ]
        config = Config(embedding_dimensions=2)
        result = get_embedding(long_text, config)
        assert result == [1.0, 2.0]
        assert mock_client.embed.call_count == 2
        # Second call should use truncated text
        second_call_input = mock_client.embed.call_args_list[1][1]["input"]
        assert second_call_input == truncated

    @patch("ragling.embeddings.ollama.Client")
    def test_short_text_still_retried_on_failure(self, mock_client_cls: MagicMock) -> None:
        """Text under 256 words still gets retried (same text since truncation is a no-op)."""
        mock_client = mock_client_cls.return_value
        short_text = "hello world"

        mock_client.embed.side_effect = [
            RuntimeError("embedding failed"),
            {"embeddings": [[1.0, 2.0]]},
        ]
        config = Config(embedding_dimensions=2)
        result = get_embedding(short_text, config)
        assert result == [1.0, 2.0]
        assert mock_client.embed.call_count == 2

    @patch("ragling.embeddings.ollama.Client")
    def test_both_attempts_fail_raises(self, mock_client_cls: MagicMock) -> None:
        """Both full and truncated attempts fail → raises exception (no zero vector)."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.side_effect = [
            RuntimeError("first failure"),
            RuntimeError("second failure"),
        ]
        config = Config(embedding_dimensions=2)
        with pytest.raises(RuntimeError, match="second failure"):
            get_embedding("some text", config)

    @patch("ragling.embeddings.ollama.Client")
    def test_connection_error_raises_immediately(self, mock_client_cls: MagicMock) -> None:
        """Connection error on first attempt raises immediately, no truncation retry."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.side_effect = ConnectionError("connection refused")
        config = Config(embedding_dimensions=2)
        with pytest.raises(OllamaConnectionError):
            get_embedding("some text", config)
        assert mock_client.embed.call_count == 1  # No retry attempted
