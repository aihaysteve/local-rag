"""Ollama model load time measurement."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
import ollama

from benchmark.matrix import BenchmarkConfig

logger = logging.getLogger(__name__)


@dataclass
class ModelLoadResult:
    """Result of a model load time measurement."""

    model: str
    model_type: str
    load_time_ms: int
    vram_bytes: int | None


def extract_unique_models(configs: list[BenchmarkConfig]) -> set[str]:
    """Extract the unique set of embedding models from configurations."""
    return {cfg.embedding_model for cfg in configs}


def _make_client(ollama_host: str | None) -> ollama.Client:
    """Create an Ollama client."""
    kwargs: dict[str, object] = {"timeout": httpx.Timeout(300.0)}
    if ollama_host:
        kwargs["host"] = ollama_host
    return ollama.Client(**kwargs)


def _get_model_memory(client: ollama.Client, model_name: str) -> int | None:
    """Query Ollama /api/ps for a model's memory usage in bytes."""
    try:
        ps_response = client.ps()
        for m in ps_response.get("models", []):
            if m.get("name", "").startswith(model_name):
                return m.get("size_vram", None)
    except Exception:
        logger.debug("Could not query model memory for %s", model_name)
    return None


def measure_model_load_times(
    configs: list[BenchmarkConfig],
    ollama_host: str | None = None,
) -> list[ModelLoadResult]:
    """Measure cold-start load time for each unique embedding model.

    For each model: unloads it, sends a warmup embed request,
    measures the time, and queries memory usage.

    Args:
        configs: List of benchmark configurations.
        ollama_host: Optional Ollama host override.

    Returns:
        List of ModelLoadResult, one per unique model.
    """
    client = _make_client(ollama_host)
    models = sorted(extract_unique_models(configs))
    results: list[ModelLoadResult] = []

    for model in models:
        logger.info("Measuring load time for model: %s", model)

        # Unload the model (set keep_alive to 0)
        try:
            client.embed(model=model, input="unload", keep_alive=0)
        except Exception:
            logger.debug("Could not unload %s (may not be loaded)", model)

        # Measure cold load
        start = time.monotonic()
        try:
            client.embed(model=model, input="benchmark warmup text")
            elapsed_ms = int((time.monotonic() - start) * 1000)
        except Exception as e:
            logger.error("Failed to load model %s: %s", model, e)
            continue

        vram = _get_model_memory(client, model)

        results.append(
            ModelLoadResult(
                model=model,
                model_type="embedding",
                load_time_ms=elapsed_ms,
                vram_bytes=vram,
            )
        )
        logger.info("  %s: %dms, %s", model, elapsed_ms, f"{vram:,} bytes" if vram else "N/A")

    return results
