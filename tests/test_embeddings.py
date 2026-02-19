"""Tests for ragling.embeddings module."""

from unittest.mock import MagicMock, patch

import pytest

from ragling.config import Config
from ragling.embeddings import (
    OllamaConnectionError,
    _client,
    _raise_if_connection_error,
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
    def test_individual_nan_returns_zero_vector(self, mock_client_cls: MagicMock) -> None:
        """Batch fails, one individual also fails → zero vector at that position."""
        mock_client = mock_client_cls.return_value

        # Batch fails, text 0 succeeds, text 1 fails (NaN), text 2 succeeds
        mock_client.embed.side_effect = [
            RuntimeError("json: unsupported value: NaN"),
            {"embeddings": [[1.0, 2.0]]},
            RuntimeError("json: unsupported value: NaN"),
            {"embeddings": [[5.0, 6.0]]},
        ]
        config = Config(embedding_dimensions=2)
        result = get_embeddings(["a", "b", "c"], config)
        assert result == [[1.0, 2.0], [0.0, 0.0], [5.0, 6.0]]

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
