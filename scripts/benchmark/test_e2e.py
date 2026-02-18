"""End-to-end smoke test for the benchmark pipeline."""

import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_full_pipeline_lightweight(tmp_path: Path) -> None:
    """Run the full benchmark pipeline with lightweight fixtures only."""
    from benchmark.fixtures import discover_fixtures
    from benchmark.matrix import parse_matrix
    from benchmark.output import render_markdown, write_csv
    from benchmark.runner import run_benchmarks

    # Create fixtures
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "test.txt").write_text("Hello world. " * 200)
    (fixtures_dir / "test.md").write_text(
        "# Title\n\nSome content here.\n\n## Section\n\nMore text.\n"
    )

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
        name = "test-config"
        embedding_model = "bge-m3"
        asr_model = "small"
        image_description = false
        code_enrichment = false
        formula_enrichment = false
        table_structure = false
    """)
    )

    matrix = parse_matrix(matrix_file)
    # Override fixtures_dir resolution
    matrix.fixtures_dir = str(fixtures_dir)

    fixtures = discover_fixtures(fixtures_dir)
    assert len(fixtures) == 2

    # Mock embeddings to avoid needing Ollama
    with patch("benchmark.runner.get_embeddings") as mock_embed:
        mock_embed.return_value = [[0.1] * 1024]  # fake embeddings

        results = run_benchmarks(matrix, fixtures, tag="test-tag")

    assert len(results) == 2  # 1 config x 2 fixtures

    # Write CSV
    csv_path = tmp_path / "results" / "benchmarks.csv"
    write_csv(results, csv_path)
    assert csv_path.exists()

    # Render markdown
    md_path = tmp_path / "results" / "benchmarks.md"
    render_markdown(csv_path, md_path)
    assert md_path.exists()

    md_content = md_path.read_text()
    assert "# Benchmark Results" in md_content
    assert "test-tag" in md_content
    assert "test-config" in md_content
