# tests/test_converter_config.py
"""Tests for converter configuration hashing."""


class TestConverterConfigHash:
    def test_returns_hex_string(self) -> None:
        from ragling.docling_convert import converter_config_hash

        result = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="fast",
        )
        assert isinstance(result, str)
        assert len(result) == 16  # truncated SHA-256

    def test_deterministic(self) -> None:
        from ragling.docling_convert import converter_config_hash

        a = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="fast",
        )
        b = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="fast",
        )
        assert a == b

    def test_different_config_different_hash(self) -> None:
        from ragling.docling_convert import converter_config_hash

        a = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="fast",
        )
        b = converter_config_hash(
            do_picture_description=False,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="fast",
        )
        assert a != b

    def test_default_hash_is_stable(self) -> None:
        """The default enriched config hash doesn't change between runs."""
        from ragling.docling_convert import converter_config_hash

        # This is the config we'll use in production
        result = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="fast",
        )
        # Just verify it's a valid hex string, not a specific value
        int(result, 16)  # will raise if not hex

    def test_vlm_backend_changes_hash(self) -> None:
        """Different VLM backends produce different hashes."""
        from ragling.docling_convert import converter_config_hash

        local_hash = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="fast",
        )
        remote_hash = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="fast",
            vlm_backend="ollama",
        )
        assert local_hash != remote_hash


def test_convert_and_chunk_uses_enrichment_config() -> None:
    """convert_and_chunk uses Config.enrichments instead of hardcoded True."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from ragling.config import Config, EnrichmentConfig
    from ragling.docling_convert import convert_and_chunk, converter_config_hash

    enrichments = EnrichmentConfig(
        image_description=False,
        code_enrichment=False,
        formula_enrichment=False,
        table_structure=False,
    )
    config = Config(enrichments=enrichments)

    expected_hash = converter_config_hash(
        do_picture_description=False,
        do_code_enrichment=False,
        do_formula_enrichment=False,
        table_mode="fast",
    )

    doc_store = MagicMock()
    doc_store.get_or_convert = MagicMock(side_effect=Exception("stop here"))

    test_file = Path("/tmp/test_benchmark_fake.pdf")
    # We don't need the file to exist since we mock doc_store

    try:
        convert_and_chunk(test_file, doc_store, config=config)
    except Exception:
        pass

    # Verify doc_store.get_or_convert was called with config_hash from enrichment flags
    call_args = doc_store.get_or_convert.call_args
    assert call_args is not None
    assert call_args.kwargs.get("config_hash") == expected_hash


def test_convert_and_chunk_passes_ollama_vlm_backend_in_hash() -> None:
    """When config has ollama_host, config_hash includes vlm_backend."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from ragling.config import Config
    from ragling.docling_convert import convert_and_chunk, converter_config_hash

    config = Config(ollama_host="http://gpu:11434")

    expected_hash = converter_config_hash(
        do_picture_description=True,
        do_code_enrichment=True,
        do_formula_enrichment=True,
        table_mode="fast",
        vlm_backend="ollama",
    )

    doc_store = MagicMock()
    doc_store.get_or_convert = MagicMock(side_effect=Exception("stop here"))

    try:
        convert_and_chunk(Path("/tmp/fake.pdf"), doc_store, config=config)
    except Exception:
        pass

    call_args = doc_store.get_or_convert.call_args
    assert call_args is not None
    assert call_args.kwargs.get("config_hash") == expected_hash
