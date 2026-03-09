"""Tests for the unified DFS walker."""

from pathlib import Path

from ragling.indexers.walker import (
    FileRoute,  # noqa: F401
    WalkResult,  # noqa: F401
    WalkStats,  # noqa: F401
    route_file,
    walk,
)


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


class TestWalk:
    """Tests for the DFS walker."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = walk(tmp_path)
        assert result.routes == []
        assert result.git_roots == set()
        assert result.stats.directories == 1  # root itself

    def test_flat_files(self, tmp_path: Path) -> None:
        (tmp_path / "readme.md").write_text("# Hello")
        (tmp_path / "main.py").write_text("print('hi')")
        (tmp_path / "data.xyz").write_text("unknown")

        result = walk(tmp_path)

        routes_by_name = {r.path.name: r for r in result.routes}
        assert "readme.md" in routes_by_name
        assert routes_by_name["readme.md"].parser == "markdown"
        assert "main.py" in routes_by_name
        assert routes_by_name["main.py"].parser == "treesitter"
        # .xyz is skipped
        assert "data.xyz" not in routes_by_name
        assert result.stats.skipped >= 1

    def test_git_repo_detection(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def hello(): pass")

        result = walk(tmp_path)

        routes_by_name = {r.path.name: r for r in result.routes}
        assert routes_by_name["main.py"].git_root == tmp_path
        assert tmp_path in result.git_roots

    def test_obsidian_vault_detection(self, tmp_path: Path) -> None:
        (tmp_path / ".obsidian").mkdir()
        (tmp_path / "note.md").write_text("# My note")

        result = walk(tmp_path)

        routes_by_name = {r.path.name: r for r in result.routes}
        assert routes_by_name["note.md"].vault_root == tmp_path

    def test_vault_nested_in_repo(self, tmp_path: Path) -> None:
        """Core regression test: vault inside repo, no duplicates."""
        (tmp_path / ".git").mkdir()
        vault = tmp_path / "notes"
        (vault / ".obsidian").mkdir(parents=True)
        (vault / "note.md").write_text("# A note")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def hello(): pass")
        (tmp_path / "SPEC.md").write_text("# Module\n## Purpose\nDoes things.")

        result = walk(tmp_path)

        routes_by_name = {r.path.name: r for r in result.routes}
        # note.md is in the vault
        assert routes_by_name["note.md"].vault_root == vault
        assert routes_by_name["note.md"].git_root == tmp_path
        assert routes_by_name["note.md"].parser == "markdown"
        # main.py is in the repo but not the vault
        assert routes_by_name["main.py"].git_root == tmp_path
        assert routes_by_name["main.py"].vault_root is None
        assert routes_by_name["main.py"].parser == "treesitter"
        # SPEC.md uses spec parser
        assert routes_by_name["SPEC.md"].parser == "spec"
        # Git root is tracked
        assert tmp_path in result.git_roots

    def test_nested_git_repo_overrides_parent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        subrepo = tmp_path / "vendor" / "lib"
        (subrepo / ".git").mkdir(parents=True)
        (subrepo / "lib.py").write_text("x = 1")
        (tmp_path / "main.py").write_text("import lib")

        result = walk(tmp_path)

        routes_by_name = {r.path.name: r for r in result.routes}
        assert routes_by_name["lib.py"].git_root == subrepo
        assert routes_by_name["main.py"].git_root == tmp_path
        assert subrepo in result.git_roots
        assert tmp_path in result.git_roots

    def test_hidden_directories_skipped(self, tmp_path: Path) -> None:
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "secret.py").write_text("x = 1")
        (tmp_path / "visible.py").write_text("y = 2")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        assert "visible.py" in names
        assert "secret.py" not in names

    def test_hidden_files_skipped(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden_file.py").write_text("x = 1")
        (tmp_path / "visible.py").write_text("y = 2")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        assert "visible.py" in names
        assert ".hidden_file.py" not in names

    def test_symlink_outside_root_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "external.py").write_text("x = 1")
        root = tmp_path / "root"
        root.mkdir()
        (root / "link").symlink_to(outside)
        (root / "local.py").write_text("y = 2")

        result = walk(root)

        names = {r.path.name for r in result.routes}
        assert "local.py" in names
        assert "external.py" not in names

    def test_stats_counts(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1")
        (tmp_path / "b.md").write_text("# B")
        (tmp_path / "c.xyz").write_text("skip me")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "d.rs").write_text("fn main() {}")

        result = walk(tmp_path)

        assert result.stats.by_parser["treesitter"] == 2  # .py, .rs
        assert result.stats.by_parser["markdown"] == 1
        assert result.stats.skipped >= 1  # .xyz
        assert result.stats.directories == 2  # root + sub

    def test_vault_and_git_same_directory(self, tmp_path: Path) -> None:
        """Edge case: both .git and .obsidian in same dir."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".obsidian").mkdir()
        (tmp_path / "note.md").write_text("# Note")

        result = walk(tmp_path)

        routes_by_name = {r.path.name: r for r in result.routes}
        assert routes_by_name["note.md"].vault_root == tmp_path
        assert routes_by_name["note.md"].git_root == tmp_path
