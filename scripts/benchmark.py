#!/usr/bin/env python3
"""Benchmark tool for ragling document processing pipeline.

Sweeps across model/enrichment configurations defined in a TOML matrix
file, runs curated fixtures through each configuration, and produces
a consolidated CSV + markdown performance report.

Usage:
    uv run python scripts/benchmark.py --matrix scripts/benchmark_matrix.toml --tag m1-local
    uv run python scripts/benchmark.py --matrix scripts/benchmark_matrix.toml --tag m1-4070ti \
        --ollama-host http://gpu-server:11434
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add scripts/ to sys.path so benchmark package is importable
sys.path.insert(0, str(Path(__file__).parent))

from benchmark.fixtures import discover_fixtures, generate_git_fixtures
from benchmark.matrix import parse_matrix
from benchmark.models import measure_model_load_times
from benchmark.output import render_markdown, write_csv
from benchmark.runner import run_benchmarks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark ragling document processing pipeline",
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        required=True,
        help="Path to TOML matrix configuration file",
    )
    parser.add_argument(
        "--tag",
        required=True,
        help="Hardware setup label (e.g., m1-local, m1-4070ti)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results"),
        help="Output directory for results (default: results/)",
    )
    parser.add_argument(
        "--ollama-host",
        default=None,
        help="Override Ollama host for all configurations",
    )
    parser.add_argument(
        "--filter",
        default=None,
        help="Only run configurations matching this name pattern",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("benchmark")

    # Parse matrix
    logger.info("Loading matrix from %s", args.matrix)
    matrix = parse_matrix(args.matrix)

    # Apply filter if specified
    if args.filter:
        matrix.configurations = [c for c in matrix.configurations if args.filter in c.name]
        if not matrix.configurations:
            logger.error("No configurations match filter '%s'", args.filter)
            sys.exit(1)
        logger.info(
            "Filtered to %d configuration(s): %s",
            len(matrix.configurations),
            ", ".join(c.name for c in matrix.configurations),
        )

    # Resolve fixtures directory relative to matrix file
    fixtures_dir = args.matrix.parent / matrix.fixtures_dir
    if not fixtures_dir.is_dir():
        logger.error("Fixtures directory not found: %s", fixtures_dir)
        sys.exit(1)

    # Generate git fixtures if needed
    logger.info("Checking git fixtures...")
    generate_git_fixtures(fixtures_dir)

    # Discover fixtures
    fixtures = discover_fixtures(fixtures_dir)
    logger.info("Found %d fixtures in %s", len(fixtures), fixtures_dir)
    for f in fixtures:
        logger.info("  %s (%s, %d KB)", f.name, f.format_group, f.file_size // 1024)

    # Phase 1: Model load times
    logger.info("=== Phase 1: Model Load Times ===")
    model_results = measure_model_load_times(matrix.configurations, ollama_host=args.ollama_host)

    # Phase 2: Benchmarks
    logger.info("=== Phase 2: Benchmarks ===")
    results = run_benchmarks(matrix, fixtures, args.tag, ollama_host=args.ollama_host)

    # Write output
    csv_path = args.output / "benchmarks.csv"
    md_path = args.output / "benchmarks.md"

    logger.info("Writing results to %s", args.output)
    write_csv(results, csv_path)
    render_markdown(csv_path, md_path, model_results=model_results)

    logger.info("Done! Results written to:")
    logger.info("  CSV: %s", csv_path)
    logger.info("  Markdown: %s", md_path)


if __name__ == "__main__":
    main()
