"""Tests for model load time measurement."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_extract_unique_models() -> None:
    """Extract unique embedding models from configurations."""
    from benchmark.matrix import BenchmarkConfig
    from benchmark.models import extract_unique_models

    configs = [
        BenchmarkConfig(
            name="fast",
            embedding_model="nomic-embed-text",
            asr_model="tiny",
            image_description=False,
            code_enrichment=False,
            formula_enrichment=False,
            table_structure=False,
        ),
        BenchmarkConfig(
            name="quality",
            embedding_model="bge-m3",
            asr_model="medium",
            image_description=True,
            code_enrichment=True,
            formula_enrichment=True,
            table_structure=True,
        ),
        BenchmarkConfig(
            name="balanced",
            embedding_model="bge-m3",
            asr_model="small",
            image_description=True,
            code_enrichment=False,
            formula_enrichment=False,
            table_structure=True,
        ),
    ]

    models = extract_unique_models(configs)
    assert models == {"nomic-embed-text", "bge-m3"}


def test_model_load_result_dataclass() -> None:
    """ModelLoadResult stores timing and memory info."""
    from benchmark.models import ModelLoadResult

    result = ModelLoadResult(
        model="bge-m3",
        model_type="embedding",
        load_time_ms=1200,
        vram_bytes=1_800_000_000,
    )
    assert result.model == "bge-m3"
    assert result.load_time_ms == 1200
    assert result.vram_bytes == 1_800_000_000
