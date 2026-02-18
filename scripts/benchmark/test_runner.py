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


def test_run_benchmarks_calls_on_result(tmp_path: Path) -> None:
    """run_benchmarks calls on_result callback after each fixture."""
    import textwrap

    from benchmark.fixtures import discover_fixtures
    from benchmark.matrix import parse_matrix
    from benchmark.runner import BenchmarkResult, run_benchmarks

    # Create fixtures
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "a.txt").write_text("Hello world. " * 50)
    (fixtures_dir / "b.txt").write_text("Another file. " * 50)

    # Create matrix
    matrix_file = tmp_path / "matrix.toml"
    matrix_file.write_text(
        textwrap.dedent("""\
        [fixtures]
        dir = "fixtures"
        [defaults]
        chunk_size_tokens = 256
        chunk_overlap_tokens = 50
        [[configurations]]
        name = "test"
        embedding_model = "bge-m3"
        asr_model = "small"
        image_description = false
        code_enrichment = false
        formula_enrichment = false
        table_structure = false
    """)
    )

    matrix = parse_matrix(matrix_file)
    matrix.fixtures_dir = str(fixtures_dir)
    fixtures = discover_fixtures(fixtures_dir)

    callback_results: list[BenchmarkResult] = []

    with patch("benchmark.runner.get_embeddings") as mock_embed:
        mock_embed.return_value = [[0.1] * 1024]
        run_benchmarks(
            matrix,
            fixtures,
            tag="test",
            on_result=lambda r: callback_results.append(r),
        )

    # Callback should have been called once per fixture
    assert len(callback_results) == 2
    assert all(isinstance(r, BenchmarkResult) for r in callback_results)


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
