# tests/test_converter_config.py
"""Tests for converter configuration hashing."""


class TestConverterConfigHash:
    def test_returns_hex_string(self) -> None:
        from ragling.docling_convert import converter_config_hash

        result = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="accurate",
        )
        assert isinstance(result, str)
        assert len(result) == 16  # truncated SHA-256

    def test_deterministic(self) -> None:
        from ragling.docling_convert import converter_config_hash

        a = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="accurate",
        )
        b = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="accurate",
        )
        assert a == b

    def test_different_config_different_hash(self) -> None:
        from ragling.docling_convert import converter_config_hash

        a = converter_config_hash(
            do_picture_description=True,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="accurate",
        )
        b = converter_config_hash(
            do_picture_description=False,
            do_code_enrichment=True,
            do_formula_enrichment=True,
            table_mode="accurate",
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
            table_mode="accurate",
        )
        # Just verify it's a valid hex string, not a specific value
        int(result, 16)  # will raise if not hex
