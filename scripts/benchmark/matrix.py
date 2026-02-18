"""TOML matrix configuration parser for benchmark tool."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ragling.config import AsrConfig, Config, EnrichmentConfig


@dataclass
class MatrixDefaults:
    """Shared defaults applied to all configurations."""

    chunk_size_tokens: int = 256
    chunk_overlap_tokens: int = 50


@dataclass
class BenchmarkConfig:
    """A single benchmark configuration to sweep."""

    name: str
    embedding_model: str
    asr_model: str
    image_description: bool
    code_enrichment: bool
    formula_enrichment: bool
    table_structure: bool

    def to_ragling_config(
        self,
        defaults: MatrixDefaults,
        ollama_host: str | None,
    ) -> Config:
        """Convert to a ragling Config for use in the pipeline."""
        return Config(
            embedding_model=self.embedding_model,
            chunk_size_tokens=defaults.chunk_size_tokens,
            chunk_overlap_tokens=defaults.chunk_overlap_tokens,
            asr=AsrConfig(model=self.asr_model),
            enrichments=EnrichmentConfig(
                image_description=self.image_description,
                code_enrichment=self.code_enrichment,
                formula_enrichment=self.formula_enrichment,
                table_structure=self.table_structure,
            ),
            ollama_host=ollama_host,
        )


@dataclass
class Matrix:
    """Parsed benchmark matrix."""

    fixtures_dir: str
    defaults: MatrixDefaults
    configurations: list[BenchmarkConfig]


def parse_matrix(path: Path) -> Matrix:
    """Parse a benchmark matrix TOML file.

    Args:
        path: Path to the TOML file.

    Returns:
        Parsed Matrix with defaults and configurations.

    Raises:
        FileNotFoundError: If the TOML file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Matrix file not found: {path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    fixtures_dir = data.get("fixtures", {}).get("dir", "scripts/fixtures")

    defaults_data = data.get("defaults", {})
    defaults = MatrixDefaults(
        chunk_size_tokens=defaults_data.get("chunk_size_tokens", 256),
        chunk_overlap_tokens=defaults_data.get("chunk_overlap_tokens", 50),
    )

    configurations: list[BenchmarkConfig] = []
    for cfg_data in data.get("configurations", []):
        configurations.append(
            BenchmarkConfig(
                name=cfg_data["name"],
                embedding_model=cfg_data["embedding_model"],
                asr_model=cfg_data["asr_model"],
                image_description=cfg_data["image_description"],
                code_enrichment=cfg_data["code_enrichment"],
                formula_enrichment=cfg_data["formula_enrichment"],
                table_structure=cfg_data["table_structure"],
            )
        )

    return Matrix(
        fixtures_dir=fixtures_dir,
        defaults=defaults,
        configurations=configurations,
    )
