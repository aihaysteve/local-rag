"""Tests for ragling.embeddings module."""

from unittest.mock import MagicMock, patch

from ragling.config import Config
from ragling.embeddings import _client


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
