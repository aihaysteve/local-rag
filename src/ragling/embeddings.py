"""Ollama embedding helpers for ragling."""

import logging
import struct
from typing import Any

import httpx
import ollama

from ragling.config import Config

logger = logging.getLogger(__name__)

# Send at most this many texts per Ollama API call to avoid timeouts
_BATCH_SIZE = 32

# Per-request timeout in seconds — generous because the first call
# triggers model loading which can take minutes on large models
_TIMEOUT = 300.0


class OllamaConnectionError(Exception):
    """Raised when Ollama is not reachable."""


def _client(config: Config) -> ollama.Client:
    """Create an Ollama client with a finite timeout.

    Args:
        config: Application configuration. If ``ollama_host`` is set,
            the client connects to that URL instead of localhost.
    """
    kwargs: dict[str, Any] = {"timeout": httpx.Timeout(_TIMEOUT)}
    if config.ollama_host:
        kwargs["host"] = config.ollama_host
    return ollama.Client(**kwargs)


def _raise_if_connection_error(e: Exception, *, config: Config) -> None:
    """Re-raise as OllamaConnectionError if the error looks like a connection issue."""
    msg = str(e).lower()
    if "connect" in msg or "refused" in msg:
        if config.ollama_host:
            detail = f"Cannot reach Ollama at {config.ollama_host}"
        else:
            detail = "Cannot connect to Ollama. Is it running? Start with: ollama serve"
        raise OllamaConnectionError(detail) from e


def _truncate_to_words(text: str, max_words: int = 256) -> str:
    """Truncate text to the first *max_words* whitespace-delimited words.

    Args:
        text: Input text.
        max_words: Maximum number of words to keep.

    Returns:
        Truncated text (or original if already within limit).
    """
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _embed_single_with_retry(client: ollama.Client, text: str, *, config: Config) -> list[float]:
    """Embed a single text with one truncation retry on failure.

    On the first failure (that is not a connection error), retries once with
    the text truncated to 256 words.  If the retry also fails, the exception
    propagates to the caller.

    Args:
        client: An Ollama client instance.
        text: Text to embed.
        config: Application configuration.

    Returns:
        Embedding vector as list of floats.

    Raises:
        OllamaConnectionError: If Ollama is not running or unreachable.
    """
    try:
        response = client.embed(model=config.embedding_model, input=text)
        return response["embeddings"][0]
    except Exception as e:
        _raise_if_connection_error(e, config=config)
        truncated = _truncate_to_words(text)
        logger.warning(
            "Embedding failed for text (%d chars), retrying with truncated text (%d chars)",
            len(text),
            len(truncated),
        )
        try:
            response = client.embed(model=config.embedding_model, input=truncated)
            return response["embeddings"][0]
        except Exception as retry_e:
            _raise_if_connection_error(retry_e, config=config)
            raise


def get_embedding(text: str, config: Config) -> list[float]:
    """Get embedding for a single text.

    On failure, retries once with the text truncated to 256 words.
    If the retry also fails, the exception is raised (no zero-vector fallback).

    Args:
        text: Text to embed.
        config: Application configuration.

    Returns:
        Embedding vector as list of floats.

    Raises:
        OllamaConnectionError: If Ollama is not running or unreachable.
    """
    return _embed_single_with_retry(_client(config), text, config=config)


def get_embeddings(texts: list[str], config: Config) -> list[list[float]]:
    """Get embeddings for a batch of texts.

    Sends texts in sub-batches to avoid timeouts on large inputs.
    Logs progress for visibility.

    Args:
        texts: List of texts to embed.
        config: Application configuration.

    Returns:
        List of embedding vectors.

    Raises:
        OllamaConnectionError: If Ollama is not running or unreachable.
    """
    if not texts:
        return []

    client = _client(config)
    all_embeddings: list[list[float]] = []

    for start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[start : start + _BATCH_SIZE]
        if len(texts) > _BATCH_SIZE:
            logger.info(
                "Embedding batch %d-%d of %d texts...",
                start + 1,
                min(start + _BATCH_SIZE, len(texts)),
                len(texts),
            )
        try:
            response = client.embed(model=config.embedding_model, input=batch)
            all_embeddings.extend(response["embeddings"])
        except Exception as e:
            _raise_if_connection_error(e, config=config)
            logger.warning("Batch embed failed, retrying %d texts individually", len(batch))
            for text in batch:
                all_embeddings.append(_embed_single_with_retry(client, text, config=config))

    return all_embeddings


def serialize_float32(vec: list[float]) -> bytes:
    """Serialize a float vector to sqlite-vec binary format.

    Args:
        vec: Embedding vector as list of floats.

    Returns:
        Packed binary representation for sqlite-vec.
    """
    return struct.pack(f"{len(vec)}f", *vec)
