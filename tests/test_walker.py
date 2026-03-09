"""Tests for the unified DFS walker."""

from pathlib import Path

from ragling.indexers.walker import (
    BUILTIN_EXCLUDES,
    ExclusionConfig,
    FileRoute,
    WalkResult,
    WalkStats,
    assign_collection,
    format_plan,
    route_file,
    walk,
)


class TestRouteFile:
    """Tests for file routing logic.  # Tests INV-6"""

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
        subrepo = tmp_path / "libs" / "mylib"
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


class TestBuiltinExcludes:
    """Tests for built-in exclusion patterns."""

    def test_node_modules_excluded(self, tmp_path: Path) -> None:
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "lodash.js").write_text("module.exports = {}")
        (tmp_path / "app.js").write_text("const _ = require('lodash')")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        assert "app.js" in names
        assert "lodash.js" not in names

    def test_pycache_excluded(self, tmp_path: Path) -> None:
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-312.pyc").write_text("")
        (tmp_path / "module.py").write_text("x = 1")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        assert "module.py" in names
        assert "module.cpython-312.pyc" not in names

    def test_venv_excluded(self, tmp_path: Path) -> None:
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /usr/bin")
        (tmp_path / "main.py").write_text("print('hi')")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        assert "main.py" in names

    def test_dist_excluded(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "bundle.js").write_text("var x = 1")
        (tmp_path / "src.js").write_text("var y = 2")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        assert "src.js" in names
        assert "bundle.js" not in names

    def test_lock_files_excluded(self, tmp_path: Path) -> None:
        (tmp_path / "package-lock.json").write_text("{}")
        (tmp_path / "uv.lock").write_text("")
        (tmp_path / "main.py").write_text("x = 1")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        assert "main.py" in names
        assert "package-lock.json" not in names
        assert "uv.lock" not in names

    def test_builtin_excludes_constant_exists(self) -> None:
        assert "node_modules/" in BUILTIN_EXCLUDES
        assert "__pycache__/" in BUILTIN_EXCLUDES
        assert "dist/" in BUILTIN_EXCLUDES
        assert "build/" in BUILTIN_EXCLUDES


class TestGitignore:
    """Tests for .gitignore pattern handling during walk."""

    def test_gitignore_excludes_files(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "app.log").write_text("log entry")
        (tmp_path / "app.py").write_text("print('hi')")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        assert "app.py" in names
        assert "app.log" not in names

    def test_gitignore_excludes_directories(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("output/\n")
        out = tmp_path / "output"
        out.mkdir()
        (out / "result.txt").write_text("result")
        (tmp_path / "input.txt").write_text("input")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        assert "input.txt" in names
        assert "result.txt" not in names

    def test_gitignore_scoped_to_subtree(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / ".gitignore").write_text("*.log\n")
        (sub / "sub.log").write_text("sub log")
        (tmp_path / "root.log").write_text("root log")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        # sub.log is excluded by sub/.gitignore
        assert "sub.log" not in names


class TestRagignore:
    """Tests for .ragignore pattern handling during walk."""

    def test_ragignore_in_directory(self, tmp_path: Path) -> None:
        (tmp_path / ".ragignore").write_text("*.draft.md\n")
        (tmp_path / "published.md").write_text("# Published")
        (tmp_path / "wip.draft.md").write_text("# WIP")

        result = walk(tmp_path)

        names = {r.path.name for r in result.routes}
        assert "published.md" in names
        assert "wip.draft.md" not in names


class TestGlobalRagignore:
    """Tests for global ragignore file."""

    def test_global_ragignore_applied(self, tmp_path: Path) -> None:
        ragignore = tmp_path / "ragignore"
        ragignore.write_text("*.draft.md\n")
        (tmp_path / "root").mkdir()
        (tmp_path / "root" / "published.md").write_text("# Published")
        (tmp_path / "root" / "wip.draft.md").write_text("# WIP")

        config = ExclusionConfig(global_ragignore_path=ragignore)
        result = walk(tmp_path / "root", exclusion_config=config)

        names = {r.path.name for r in result.routes}
        assert "published.md" in names
        assert "wip.draft.md" not in names

    def test_per_group_ragignore_replaces_global(self, tmp_path: Path) -> None:
        global_ignore = tmp_path / "global_ragignore"
        global_ignore.write_text("*.draft.md\n")
        group_ignore = tmp_path / "group_ragignore"
        group_ignore.write_text("*.wip.md\n")
        root = tmp_path / "root"
        root.mkdir()
        (root / "a.draft.md").write_text("# Draft")
        (root / "b.wip.md").write_text("# WIP")
        (root / "c.md").write_text("# Normal")

        config = ExclusionConfig(
            global_ragignore_path=global_ignore,
            group_ragignore_path=group_ignore,
        )
        result = walk(root, exclusion_config=config)

        names = {r.path.name for r in result.routes}
        # Group ragignore replaces global, so *.draft.md is NOT excluded
        assert "a.draft.md" in names
        # But *.wip.md IS excluded by group ragignore
        assert "b.wip.md" not in names
        assert "c.md" in names

    def test_negation_in_ragignore(self, tmp_path: Path) -> None:
        ragignore = tmp_path / "ragignore"
        ragignore.write_text("*.log\n!important.log\n")
        root = tmp_path / "root"
        root.mkdir()
        (root / "debug.log").write_text("debug")
        (root / "important.log").write_text("important")

        config = ExclusionConfig(global_ragignore_path=ragignore)
        result = walk(root, exclusion_config=config)

        names = {r.path.name for r in result.routes}
        assert "important.log" in names
        assert "debug.log" not in names


class TestAssignCollection:
    """Tests for collection assignment.  # Tests INV-6"""

    def test_vault_file_gets_vault_collection(self, tmp_path: Path) -> None:
        vault = tmp_path / "notes"
        route = FileRoute(
            path=vault / "note.md",
            parser="markdown",
            git_root=tmp_path,
            vault_root=vault,
        )
        coll = assign_collection(route, watch_name="workspace", watch_root=tmp_path)
        assert coll == "workspace/notes"

    def test_repo_file_gets_repo_collection(self, tmp_path: Path) -> None:
        repo = tmp_path / "myrepo"
        route = FileRoute(
            path=repo / "main.py",
            parser="treesitter",
            git_root=repo,
            vault_root=None,
        )
        coll = assign_collection(route, watch_name="workspace", watch_root=tmp_path)
        assert coll == "workspace/myrepo"

    def test_plain_file_gets_watch_collection(self, tmp_path: Path) -> None:
        route = FileRoute(
            path=tmp_path / "readme.txt",
            parser="plaintext",
            git_root=None,
            vault_root=None,
        )
        coll = assign_collection(route, watch_name="workspace", watch_root=tmp_path)
        assert coll == "workspace"

    def test_root_level_repo_gets_watch_collection(self, tmp_path: Path) -> None:
        """When git_root IS the watch_root, use watch_name directly."""
        route = FileRoute(
            path=tmp_path / "main.py",
            parser="treesitter",
            git_root=tmp_path,
            vault_root=None,
        )
        coll = assign_collection(route, watch_name="workspace", watch_root=tmp_path)
        assert coll == "workspace"

    def test_root_level_vault_gets_watch_collection(self, tmp_path: Path) -> None:
        """When vault_root IS the watch_root, use watch_name directly."""
        route = FileRoute(
            path=tmp_path / "note.md",
            parser="markdown",
            git_root=None,
            vault_root=tmp_path,
        )
        coll = assign_collection(route, watch_name="workspace", watch_root=tmp_path)
        assert coll == "workspace"

    def test_deeply_nested_vault_in_repo(self, tmp_path: Path) -> None:
        vault = tmp_path / "project" / "docs" / "vault"
        route = FileRoute(
            path=vault / "note.md",
            parser="markdown",
            git_root=tmp_path / "project",
            vault_root=vault,
        )
        coll = assign_collection(route, watch_name="ws", watch_root=tmp_path)
        assert coll == "ws/project/docs/vault"


class TestFormatPlan:
    """Tests for dry-run plan formatting."""

    def test_format_plan_shows_counts(self, tmp_path: Path) -> None:
        result = WalkResult(
            routes=[
                FileRoute(tmp_path / "a.py", "treesitter", None, None),
                FileRoute(tmp_path / "b.md", "markdown", None, None),
            ],
            git_roots=set(),
            stats=WalkStats(
                by_parser={"treesitter": 1, "markdown": 1},
                skipped=2,
                directories=3,
            ),
        )
        output = format_plan(result, watch_name="test", watch_root=tmp_path)
        assert "2 files" in output
        assert "3 directories" in output
        assert "treesitter" in output
        assert "markdown" in output
        assert "skipped" in output.lower() or "2" in output

    def test_format_plan_shows_git_roots(self, tmp_path: Path) -> None:
        result = WalkResult(
            routes=[],
            git_roots={tmp_path / "repo1", tmp_path / "repo2"},
            stats=WalkStats(directories=1),
        )
        output = format_plan(result, watch_name="test", watch_root=tmp_path)
        assert "2" in output  # 2 repos
