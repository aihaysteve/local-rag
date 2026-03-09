"""Tests for the unified DFS walker."""

from pathlib import Path

from ragling.indexers.walker import route_file


class TestRouteFile:
    """Tests for file routing logic.  # Tests INV-10"""

    def test_spec_md_routes_to_spec(self) -> None:
        assert route_file(Path("SPEC.md")) == "spec"

    def test_spec_md_in_subdirectory(self) -> None:
        assert route_file(Path("src/ragling/SPEC.md")) == "spec"

    def test_pdf_routes_to_docling(self) -> None:
        assert route_file(Path("report.pdf")) == "docling"

    def test_docx_routes_to_docling(self) -> None:
        assert route_file(Path("doc.docx")) == "docling"

    def test_pptx_routes_to_docling(self) -> None:
        assert route_file(Path("slides.pptx")) == "docling"

    def test_xlsx_routes_to_docling(self) -> None:
        assert route_file(Path("data.xlsx")) == "docling"

    def test_html_routes_to_docling(self) -> None:
        assert route_file(Path("page.html")) == "docling"

    def test_htm_routes_to_docling(self) -> None:
        assert route_file(Path("page.htm")) == "docling"

    def test_epub_routes_to_docling(self) -> None:
        assert route_file(Path("book.epub")) == "docling"

    def test_image_routes_to_docling(self) -> None:
        assert route_file(Path("photo.png")) == "docling"

    def test_audio_routes_to_docling(self) -> None:
        assert route_file(Path("recording.mp3")) == "docling"

    def test_markdown_routes_to_markdown(self) -> None:
        assert route_file(Path("notes.md")) == "markdown"

    def test_markdown_uppercase_extension(self) -> None:
        assert route_file(Path("README.MD")) == "markdown"

    def test_python_routes_to_treesitter(self) -> None:
        assert route_file(Path("main.py")) == "treesitter"

    def test_rust_routes_to_treesitter(self) -> None:
        assert route_file(Path("lib.rs")) == "treesitter"

    def test_javascript_routes_to_treesitter(self) -> None:
        assert route_file(Path("app.js")) == "treesitter"

    def test_typescript_routes_to_treesitter(self) -> None:
        assert route_file(Path("index.ts")) == "treesitter"

    def test_go_routes_to_treesitter(self) -> None:
        assert route_file(Path("main.go")) == "treesitter"

    def test_yaml_routes_to_treesitter(self) -> None:
        assert route_file(Path("config.yaml")) == "treesitter"

    def test_yml_routes_to_treesitter(self) -> None:
        assert route_file(Path("config.yml")) == "treesitter"

    def test_toml_routes_to_treesitter(self) -> None:
        assert route_file(Path("pyproject.toml")) == "treesitter"

    def test_dockerfile_routes_to_treesitter(self) -> None:
        assert route_file(Path("Dockerfile")) == "treesitter"

    def test_makefile_routes_to_treesitter(self) -> None:
        assert route_file(Path("Makefile")) == "treesitter"

    def test_txt_routes_to_plaintext(self) -> None:
        assert route_file(Path("readme.txt")) == "plaintext"

    def test_csv_routes_to_docling(self) -> None:
        assert route_file(Path("data.csv")) == "docling"

    def test_log_routes_to_plaintext(self) -> None:
        assert route_file(Path("app.log")) == "plaintext"

    def test_ini_routes_to_plaintext(self) -> None:
        assert route_file(Path("config.ini")) == "plaintext"

    def test_unknown_extension_routes_to_skip(self) -> None:
        assert route_file(Path("file.xyz")) == "skip"

    def test_no_extension_routes_to_skip(self) -> None:
        assert route_file(Path("LICENSE")) == "skip"

    def test_binary_routes_to_skip(self) -> None:
        assert route_file(Path("image.ico")) == "skip"

    def test_spec_md_takes_priority_over_markdown(self) -> None:
        """SPEC.md should be routed to spec parser, not markdown."""
        assert route_file(Path("SPEC.md")) == "spec"

    def test_json_routes_to_treesitter(self) -> None:
        """JSON has tree-sitter grammar, should use it."""
        assert route_file(Path("package.json")) == "treesitter"

    def test_xml_routes_to_treesitter(self) -> None:
        assert route_file(Path("pom.xml")) == "treesitter"

    def test_sql_routes_to_treesitter(self) -> None:
        assert route_file(Path("schema.sql")) == "treesitter"
