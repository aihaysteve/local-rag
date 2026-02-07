"""Ollama embedding helpers for local-rag."""

import logging
import struct

import ollama

from local_rag.config import Config

logger = logging.getLogger(__name__)


class OllamaConnectionError(Exception):
    """Raised when Ollama is not reachable."""


def get_embedding(text: str, config: Config) -> list[float]:
    """Get embedding for a single text.

    Args:
        text: Text to embed.
        config: Application configuration.

    Returns:
        Embedding vector as list of floats.

    Raises:
        OllamaConnectionError: If Ollama is not running or unreachable.
    """
    try:
        response = ollama.embed(model=config.embedding_model, input=text)
        return response["embeddings"][0]
    except Exception as e:
        if "connect" in str(e).lower() or "refused" in str(e).lower():
            raise OllamaConnectionError(
                "Cannot connect to Ollama. Is it running? Start with: ollama serve"
            ) from e
        raise


def get_embeddings(texts: list[str], config: Config) -> list[list[float]]:
    """Get embeddings for a batch of texts.

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

    try:
        response = ollama.embed(model=config.embedding_model, input=texts)
        return response["embeddings"]
    except Exception as e:
        if "connect" in str(e).lower() or "refused" in str(e).lower():
            raise OllamaConnectionError(
                "Cannot connect to Ollama. Is it running? Start with: ollama serve"
            ) from e
        raise


def serialize_float32(vec: list[float]) -> bytes:
    """Serialize a float vector to sqlite-vec binary format.

    Args:
        vec: Embedding vector as list of floats.

    Returns:
        Packed binary representation for sqlite-vec.
    """
    return struct.pack(f"{len(vec)}f", *vec)
