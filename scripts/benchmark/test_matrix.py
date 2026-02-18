"""Tests for benchmark matrix TOML parser."""

import sys
import textwrap
from pathlib import Path

import pytest

# Ensure scripts dir is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_parse_matrix_minimal(tmp_path: Path) -> None:
    """Parse a minimal matrix with one configuration."""
    from benchmark.matrix import BenchmarkConfig, parse_matrix

    toml_file = tmp_path / "matrix.toml"
    toml_file.write_text(
        textwrap.dedent("""\
        [fixtures]
        dir = "scripts/fixtures"

        [defaults]
        chunk_size_tokens = 256
        chunk_overlap_tokens = 50

        [[configurations]]
        name = "fast"
        embedding_model = "nomic-embed-text"
        asr_model = "tiny"
        image_description = false
        code_enrichment = false
        formula_enrichment = false
        table_structure = false
    """)
    )

    matrix = parse_matrix(toml_file)
    assert matrix.fixtures_dir == "scripts/fixtures"
    assert matrix.defaults.chunk_size_tokens == 256
    assert len(matrix.configurations) == 1

    cfg = matrix.configurations[0]
    assert isinstance(cfg, BenchmarkConfig)
    assert cfg.name == "fast"
    assert cfg.embedding_model == "nomic-embed-text"
    assert cfg.asr_model == "tiny"
    assert cfg.image_description is False


def test_parse_matrix_multiple_configs(tmp_path: Path) -> None:
    """Parse a matrix with multiple configurations."""
    from benchmark.matrix import parse_matrix

    toml_file = tmp_path / "matrix.toml"
    toml_file.write_text(
        textwrap.dedent("""\
        [fixtures]
        dir = "fixtures"

        [defaults]
        chunk_size_tokens = 256
        chunk_overlap_tokens = 50

        [[configurations]]
        name = "fast"
        embedding_model = "nomic-embed-text"
        asr_model = "tiny"
        image_description = false
        code_enrichment = false
        formula_enrichment = false
        table_structure = false

        [[configurations]]
        name = "quality"
        embedding_model = "bge-m3"
        asr_model = "medium"
        image_description = true
        code_enrichment = true
        formula_enrichment = true
        table_structure = true
    """)
    )

    matrix = parse_matrix(toml_file)
    assert len(matrix.configurations) == 2
    assert matrix.configurations[0].name == "fast"
    assert matrix.configurations[1].name == "quality"
    assert matrix.configurations[1].image_description is True


def test_parse_matrix_missing_file() -> None:
    """Raise FileNotFoundError for missing TOML file."""
    from benchmark.matrix import parse_matrix

    with pytest.raises(FileNotFoundError):
        parse_matrix(Path("/nonexistent/matrix.toml"))


def test_benchmark_config_to_ragling_config() -> None:
    """BenchmarkConfig.to_ragling_config() produces a valid Config."""
    from benchmark.matrix import BenchmarkConfig, MatrixDefaults

    defaults = MatrixDefaults(chunk_size_tokens=128, chunk_overlap_tokens=25)
    cfg = BenchmarkConfig(
        name="test",
        embedding_model="nomic-embed-text",
        asr_model="tiny",
        image_description=False,
        code_enrichment=False,
        formula_enrichment=False,
        table_structure=False,
    )

    ragling_config = cfg.to_ragling_config(defaults, ollama_host=None)
    assert ragling_config.embedding_model == "nomic-embed-text"
    assert ragling_config.asr.model == "tiny"
    assert ragling_config.enrichments.image_description is False
    assert ragling_config.chunk_size_tokens == 128
