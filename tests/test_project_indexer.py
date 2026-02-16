"""Tests for ragling.indexers.project module -- format routing."""

import inspect

from ragling.indexers.project import _EXTENSION_MAP


class TestExtensionMap:
    def test_pdf_maps_to_pdf(self) -> None:
        assert _EXTENSION_MAP[".pdf"] == "pdf"

    def test_docx_maps_to_docx(self) -> None:
        assert _EXTENSION_MAP[".docx"] == "docx"

    def test_pptx_maps_to_pptx(self) -> None:
        assert _EXTENSION_MAP[".pptx"] == "pptx"

    def test_xlsx_maps_to_xlsx(self) -> None:
        assert _EXTENSION_MAP[".xlsx"] == "xlsx"

    def test_tex_maps_to_latex(self) -> None:
        assert _EXTENSION_MAP[".tex"] == "latex"

    def test_latex_maps_to_latex(self) -> None:
        assert _EXTENSION_MAP[".latex"] == "latex"

    def test_png_maps_to_image(self) -> None:
        assert _EXTENSION_MAP[".png"] == "image"

    def test_jpg_maps_to_image(self) -> None:
        assert _EXTENSION_MAP[".jpg"] == "image"

    def test_jpeg_maps_to_image(self) -> None:
        assert _EXTENSION_MAP[".jpeg"] == "image"

    def test_tiff_maps_to_image(self) -> None:
        assert _EXTENSION_MAP[".tiff"] == "image"

    def test_md_maps_to_markdown(self) -> None:
        assert _EXTENSION_MAP[".md"] == "markdown"

    def test_adoc_maps_to_asciidoc(self) -> None:
        assert _EXTENSION_MAP[".adoc"] == "asciidoc"

    def test_epub_maps_to_epub(self) -> None:
        assert _EXTENSION_MAP[".epub"] == "epub"

    def test_csv_maps_to_csv(self) -> None:
        assert _EXTENSION_MAP[".csv"] == "csv"

    def test_html_maps_to_html(self) -> None:
        assert _EXTENSION_MAP[".html"] == "html"

    def test_htm_maps_to_html(self) -> None:
        assert _EXTENSION_MAP[".htm"] == "html"

    def test_txt_maps_to_plaintext(self) -> None:
        assert _EXTENSION_MAP[".txt"] == "plaintext"

    def test_json_maps_to_plaintext(self) -> None:
        assert _EXTENSION_MAP[".json"] == "plaintext"

    def test_yaml_maps_to_plaintext(self) -> None:
        assert _EXTENSION_MAP[".yaml"] == "plaintext"

    def test_yml_maps_to_plaintext(self) -> None:
        assert _EXTENSION_MAP[".yml"] == "plaintext"


class TestDoclingRouting:
    def test_docling_formats_imported(self) -> None:
        """DOCLING_FORMATS is accessible from project module."""
        from ragling.docling_convert import DOCLING_FORMATS

        assert "pdf" in DOCLING_FORMATS
        assert "markdown" not in DOCLING_FORMATS

    def test_all_docling_extensions_have_mapping(self) -> None:
        """Every format in DOCLING_FORMATS has at least one extension mapping to it."""
        from ragling.docling_convert import DOCLING_FORMATS

        mapped_formats = set(_EXTENSION_MAP.values())
        for fmt in DOCLING_FORMATS:
            assert fmt in mapped_formats, f"DOCLING_FORMATS has '{fmt}' but no extension maps to it"

    def test_parse_and_chunk_accepts_doc_store(self) -> None:
        """_parse_and_chunk accepts optional doc_store parameter."""
        from ragling.indexers.project import _parse_and_chunk

        sig = inspect.signature(_parse_and_chunk)
        assert "doc_store" in sig.parameters

    def test_project_indexer_accepts_doc_store(self) -> None:
        """ProjectIndexer accepts optional doc_store parameter."""
        from ragling.indexers.project import ProjectIndexer

        sig = inspect.signature(ProjectIndexer.__init__)
        assert "doc_store" in sig.parameters


class TestObsidianDoclingRouting:
    def test_obsidian_index_file_accepts_doc_store(self) -> None:
        """_index_file in obsidian indexer accepts doc_store parameter."""
        from ragling.indexers.obsidian import _index_file

        sig = inspect.signature(_index_file)
        assert "doc_store" in sig.parameters

    def test_obsidian_indexer_index_accepts_doc_store(self) -> None:
        """ObsidianIndexer.index() accepts doc_store parameter."""
        from ragling.indexers.obsidian import ObsidianIndexer

        sig = inspect.signature(ObsidianIndexer.index)
        assert "doc_store" in sig.parameters
