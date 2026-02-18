"""Tests for the benchmark runner."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_benchmark_result_dataclass() -> None:
    """BenchmarkResult stores all timing columns."""
    from benchmark.runner import BenchmarkResult

    result = BenchmarkResult(
        tag="m1-local",
        configuration="fast",
        fixture="test.pdf",
        format_group="pdf",
        file_size_kb=2048,
        conversion_ms=12340,
        chunking_ms=89,
        embedding_ms=1200,
        total_ms=13629,
        chunks_produced=47,
    )
    assert result.tag == "m1-local"
    assert result.total_ms == 13629


def test_time_conversion_plaintext(tmp_path: Path) -> None:
    """time_conversion returns elapsed ms and chunks for a plaintext file via the bridge path."""
    from benchmark.runner import time_conversion
    from ragling.config import Config, EnrichmentConfig

    # Create a fake text file (plaintext goes through bridge, not Docling)
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello world. " * 50)

    config = Config(
        enrichments=EnrichmentConfig(
            image_description=False,
            code_enrichment=False,
            formula_enrichment=False,
            table_structure=False,
        ),
    )

    elapsed_ms, chunks = time_conversion(test_file, "plaintext", config, doc_store=None)
    assert elapsed_ms >= 0
    assert isinstance(chunks, list)
    assert len(chunks) > 0


def test_time_embedding() -> None:
    """time_embedding returns elapsed ms."""
    from benchmark.runner import time_embedding
    from ragling.config import Config

    with patch("benchmark.runner.get_embeddings") as mock_embed:
        mock_embed.return_value = [[0.1, 0.2]] * 3
        config = Config()

        elapsed_ms = time_embedding(["text1", "text2", "text3"], config)
        assert elapsed_ms >= 0
        mock_embed.assert_called_once()
