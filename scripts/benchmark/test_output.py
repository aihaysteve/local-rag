"""Tests for benchmark output (CSV + markdown)."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark.runner import BenchmarkResult


def _make_result(**overrides: object) -> BenchmarkResult:
    defaults = dict(
        tag="m1-local",
        configuration="fast",
        fixture="test.pdf",
        format_group="pdf",
        file_size_kb=100,
        conversion_ms=1000,
        chunking_ms=50,
        embedding_ms=200,
        total_ms=1250,
        chunks_produced=10,
    )
    defaults.update(overrides)
    return BenchmarkResult(**defaults)  # type: ignore[arg-type]


def test_write_csv_creates_file(tmp_path: Path) -> None:
    """write_csv creates a new CSV file with headers."""
    from benchmark.output import write_csv

    csv_path = tmp_path / "results.csv"
    results = [_make_result()]

    write_csv(results, csv_path)

    assert csv_path.exists()
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["tag"] == "m1-local"
    assert rows[0]["total_ms"] == "1250"


def test_write_csv_upserts(tmp_path: Path) -> None:
    """write_csv upserts by (tag, configuration, fixture) key."""
    from benchmark.output import write_csv

    csv_path = tmp_path / "results.csv"

    write_csv([_make_result(total_ms=1000)], csv_path)
    write_csv([_make_result(total_ms=2000)], csv_path)

    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["total_ms"] == "2000"


def test_write_csv_preserves_other_rows(tmp_path: Path) -> None:
    """write_csv preserves rows from other tags when upserting."""
    from benchmark.output import write_csv

    csv_path = tmp_path / "results.csv"

    write_csv([_make_result(tag="m1-local")], csv_path)
    write_csv([_make_result(tag="m1-4070ti", total_ms=800)], csv_path)

    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    tags = {r["tag"] for r in rows}
    assert tags == {"m1-local", "m1-4070ti"}


def test_render_markdown(tmp_path: Path) -> None:
    """render_markdown produces a markdown file with tables."""
    from benchmark.output import render_markdown, write_csv

    csv_path = tmp_path / "results.csv"
    md_path = tmp_path / "results.md"

    results = [
        _make_result(tag="m1-local", configuration="fast", fixture="a.pdf"),
        _make_result(tag="m1-local", configuration="balanced", fixture="a.pdf", total_ms=2000),
    ]
    write_csv(results, csv_path)
    render_markdown(csv_path, md_path)

    content = md_path.read_text()
    assert "# Benchmark Results" in content
    assert "fast" in content
    assert "balanced" in content
    assert "m1-local" in content
