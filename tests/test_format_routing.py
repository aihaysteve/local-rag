"""Tests for indexers.format_routing — shared format dispatch."""

from pathlib import Path


class TestExtensionMap:
    """EXTENSION_MAP provides correct source type mappings."""

    def test_pdf_maps_to_pdf(self) -> None:
        from ragling.indexers.format_routing import EXTENSION_MAP

        assert EXTENSION_MAP[".pdf"] == "pdf"

    def test_md_maps_to_markdown(self) -> None:
        from ragling.indexers.format_routing import EXTENSION_MAP

        assert EXTENSION_MAP[".md"] == "markdown"

    def test_txt_maps_to_plaintext(self) -> None:
        from ragling.indexers.format_routing import EXTENSION_MAP

        assert EXTENSION_MAP[".txt"] == "plaintext"

    def test_is_dict(self) -> None:
        from ragling.indexers.format_routing import EXTENSION_MAP

        assert isinstance(EXTENSION_MAP, dict)
        assert len(EXTENSION_MAP) > 30  # sanity check


class TestParseAndChunk:
    """parse_and_chunk routes to correct parser by source type."""

    def test_markdown_returns_chunks(self, tmp_path: Path) -> None:
        from ragling.config import Config
        from ragling.indexers.format_routing import parse_and_chunk

        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello\n\nSome content here.")
        config = Config()
        chunks = parse_and_chunk(md_file, "markdown", config)
        assert len(chunks) >= 1
        assert "Hello" in chunks[0].text or "content" in chunks[0].text

    def test_unknown_source_type_returns_empty(self, tmp_path: Path) -> None:
        from ragling.config import Config
        from ragling.indexers.format_routing import parse_and_chunk

        f = tmp_path / "test.xyz"
        f.write_text("content")
        config = Config()
        chunks = parse_and_chunk(f, "unknown_type", config)
        assert chunks == []

    def test_plaintext_returns_chunks(self, tmp_path: Path) -> None:
        from ragling.config import Config
        from ragling.indexers.format_routing import parse_and_chunk

        f = tmp_path / "test.txt"
        f.write_text("Some plain text content that should be chunked.")
        config = Config()
        chunks = parse_and_chunk(f, "plaintext", config)
        assert len(chunks) >= 1


class TestSupportedExtensions:
    """SUPPORTED_EXTENSIONS still accessible from project.py for backwards compat."""

    def test_available_from_project(self) -> None:
        from ragling.indexers.project import _SUPPORTED_EXTENSIONS

        assert isinstance(_SUPPORTED_EXTENSIONS, frozenset)
        assert ".py" in _SUPPORTED_EXTENSIONS
        assert ".md" in _SUPPORTED_EXTENSIONS

    def test_available_from_format_routing(self) -> None:
        from ragling.indexers.format_routing import SUPPORTED_EXTENSIONS

        assert isinstance(SUPPORTED_EXTENSIONS, frozenset)
        assert ".py" in SUPPORTED_EXTENSIONS
        assert ".md" in SUPPORTED_EXTENSIONS


class TestPublicImports:
    """format_routing exports are importable with public names."""

    def test_extension_map_importable(self) -> None:
        from ragling.indexers.format_routing import EXTENSION_MAP

        assert EXTENSION_MAP is not None

    def test_parse_and_chunk_importable(self) -> None:
        from ragling.indexers.format_routing import parse_and_chunk

        assert callable(parse_and_chunk)

    def test_supported_extensions_importable(self) -> None:
        from ragling.indexers.format_routing import SUPPORTED_EXTENSIONS

        assert SUPPORTED_EXTENSIONS is not None

    def test_is_supported_extension_importable(self) -> None:
        from ragling.indexers.format_routing import is_supported_extension

        assert callable(is_supported_extension)
