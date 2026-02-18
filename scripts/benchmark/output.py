"""CSV and markdown output for benchmark results."""

from __future__ import annotations

import csv
from dataclasses import asdict, fields
from pathlib import Path

from benchmark.models import ModelLoadResult
from benchmark.runner import BenchmarkResult

_CSV_FIELDS = [f.name for f in fields(BenchmarkResult)]


def write_csv(results: list[BenchmarkResult], csv_path: Path) -> None:
    """Write benchmark results to CSV with upsert semantics.

    Upserts by (tag, configuration, fixture) key — existing rows
    with the same key are replaced, other rows are preserved.

    Args:
        results: New benchmark results to write.
        csv_path: Path to the CSV file (created if missing).
    """
    existing: dict[tuple[str, str, str], dict[str, str]] = {}

    if csv_path.exists():
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["tag"], row["configuration"], row["fixture"])
                existing[key] = row

    for result in results:
        key = (result.tag, result.configuration, result.fixture)
        existing[key] = {k: str(v) for k, v in asdict(result).items()}

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in existing.values():
            writer.writerow(row)


def _format_time(ms_str: str) -> str:
    """Format milliseconds as human-readable time."""
    ms = int(ms_str)
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


def _format_size(kb: int) -> str:
    """Format kilobytes as human-readable size."""
    if kb < 1024:
        return f"{kb} KB"
    return f"{kb / 1024:.1f} MB"


def _format_bytes(b: int | None) -> str:
    """Format bytes as human-readable size."""
    if b is None:
        return "N/A"
    gb = b / (1024**3)
    if gb >= 1:
        return f"{gb:.1f} GB"
    mb = b / (1024**2)
    return f"{mb:.0f} MB"


def _format_time_ms(ms: int) -> str:
    """Format milliseconds as human-readable time (from int, not string)."""
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


def format_result_line(result: BenchmarkResult) -> str:
    """Format a single benchmark result as a one-line stage breakdown.

    Output format: [config] fixture  conv:Xs  embed:Xs  total:Xs  (N chunks)

    Args:
        result: A single benchmark result.

    Returns:
        Formatted string for printing to stdout.
    """
    conv = _format_time_ms(result.conversion_ms)
    embed = _format_time_ms(result.embedding_ms)
    total = _format_time_ms(result.total_ms)
    return (
        f"[{result.configuration}] {result.fixture:<30s} "
        f"conv:{conv}  embed:{embed}  total:{total}  "
        f"({result.chunks_produced} chunks)"
    )


def render_markdown(
    csv_path: Path,
    md_path: Path,
    model_results: list[ModelLoadResult] | None = None,
) -> None:
    """Render consolidated CSV as a markdown report.

    Produces: summary table, model load times, per-format-group tables.

    Args:
        csv_path: Path to the consolidated CSV.
        md_path: Path to write the markdown output.
        model_results: Optional model load time measurements.
    """
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    if not rows:
        md_path.write_text("# Benchmark Results\n\nNo results yet.\n")
        return

    # Collect unique tags and configurations
    tag_configs: dict[str, set[str]] = {}
    for row in rows:
        tag_configs.setdefault(row["tag"], set()).add(row["configuration"])

    # Build column headers: tag/configuration combos
    columns: list[tuple[str, str]] = []
    for tag in sorted(tag_configs):
        for config in sorted(tag_configs[tag]):
            columns.append((tag, config))

    col_labels = [f"{tag}/{config}" for tag, config in columns]

    lines: list[str] = ["# Benchmark Results\n"]

    # --- Summary table ---
    lines.append("## Summary (avg total seconds per file)\n")

    all_tags = sorted({row["tag"] for row in rows})
    all_configs = sorted({row["configuration"] for row in rows})

    # Calculate averages
    config_tag_totals: dict[str, dict[str, float]] = {}
    config_tag_counts: dict[str, dict[str, int]] = {}
    for row in rows:
        cfg = row["configuration"]
        tag = row["tag"]
        config_tag_totals.setdefault(cfg, {}).setdefault(tag, 0.0)
        config_tag_totals[cfg][tag] += int(row["total_ms"])
        config_tag_counts.setdefault(cfg, {}).setdefault(tag, 0)
        config_tag_counts[cfg][tag] += 1

    lines.append("| Configuration | " + " | ".join(all_tags) + " |")
    lines.append("|" + "---|" * (len(all_tags) + 1))
    for cfg in all_configs:
        cells = []
        for tag in all_tags:
            total = config_tag_totals.get(cfg, {}).get(tag, 0)
            count = config_tag_counts.get(cfg, {}).get(tag, 0)
            if count > 0:
                avg_s = (total / count) / 1000
                cells.append(f"{avg_s:.1f}s")
            else:
                cells.append("-")
        lines.append(f"| {cfg} | " + " | ".join(cells) + " |")
    lines.append("")

    # --- Model load times ---
    if model_results:
        lines.append("## Model Load Times\n")
        lines.append("| Model | Type | Load Time | VRAM/RAM |")
        lines.append("|---|---|---|---|")
        for m in model_results:
            lines.append(
                f"| {m.model} | {m.model_type} "
                f"| {_format_time(str(m.load_time_ms))} "
                f"| {_format_bytes(m.vram_bytes)} |"
            )
        lines.append("")

    # --- Per-format tables ---
    format_groups = sorted({row["format_group"] for row in rows})
    for group in format_groups:
        group_rows = [r for r in rows if r["format_group"] == group]
        fixtures_in_group = sorted({r["fixture"] for r in group_rows})

        lines.append(f"## {group.title()}\n")
        lines.append("| Fixture | Size | " + " | ".join(col_labels) + " |")
        lines.append("|---|---|" + "---|" * len(col_labels))

        for fixture_name in fixtures_in_group:
            fixture_rows = [r for r in group_rows if r["fixture"] == fixture_name]
            size = _format_size(int(fixture_rows[0]["file_size_kb"]))
            cells = []
            for tag, config in columns:
                match = [
                    r for r in fixture_rows if r["tag"] == tag and r["configuration"] == config
                ]
                if match:
                    cells.append(_format_time(match[0]["total_ms"]))
                else:
                    cells.append("-")
            lines.append(f"| {fixture_name} | {size} | " + " | ".join(cells) + " |")
        lines.append("")

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines))
