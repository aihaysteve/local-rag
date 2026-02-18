"""Tests for fixture discovery and git repo generation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_discover_fixtures(tmp_path: Path) -> None:
    """discover_fixtures finds and categorizes files by format."""
    from benchmark.fixtures import discover_fixtures

    (tmp_path / "test.pdf").write_bytes(b"%PDF-fake")
    (tmp_path / "test.md").write_text("# Hello")
    (tmp_path / "test.mp3").write_bytes(b"\x00" * 100)

    fixtures = discover_fixtures(tmp_path)
    assert len(fixtures) == 3

    names = {f.name for f in fixtures}
    assert names == {"test.pdf", "test.md", "test.mp3"}

    pdf_fixture = next(f for f in fixtures if f.name == "test.pdf")
    assert pdf_fixture.format_group == "pdf"
    assert pdf_fixture.file_size > 0


def test_discover_fixtures_skips_subdirs(tmp_path: Path) -> None:
    """discover_fixtures only looks at top-level files, not subdirectories."""
    from benchmark.fixtures import discover_fixtures

    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.pdf").write_bytes(b"%PDF-fake")
    (tmp_path / "top.pdf").write_bytes(b"%PDF-fake")

    fixtures = discover_fixtures(tmp_path)
    assert len(fixtures) == 1
    assert fixtures[0].name == "top.pdf"


def test_generate_git_fixtures(tmp_path: Path) -> None:
    """generate_git_fixtures creates small and large repos."""
    from benchmark.fixtures import generate_git_fixtures

    generate_git_fixtures(tmp_path)

    small = tmp_path / "git-repo-small"
    large = tmp_path / "git-repo-large"

    assert small.is_dir()
    assert (small / ".git").is_dir()
    assert large.is_dir()
    assert (large / ".git").is_dir()

    small_files = list(small.glob("*.py"))
    assert 5 <= len(small_files) <= 15

    large_files = list(
        f for f in large.rglob("*")
        if f.is_file() and ".git" not in str(f)
    )
    assert len(large_files) >= 50


def test_generate_git_fixtures_idempotent(tmp_path: Path) -> None:
    """generate_git_fixtures skips if repos already exist."""
    from benchmark.fixtures import generate_git_fixtures

    generate_git_fixtures(tmp_path)
    mtime = (tmp_path / "git-repo-small" / ".git").stat().st_mtime

    generate_git_fixtures(tmp_path)
    assert (tmp_path / "git-repo-small" / ".git").stat().st_mtime == mtime


FORMAT_GROUP_MAP = {
    ".pdf": "pdf",
    ".docx": "office",
    ".pptx": "office",
    ".md": "lightweight",
    ".txt": "lightweight",
    ".epub": "lightweight",
    ".mp3": "audio",
    ".wav": "audio",
    ".jpg": "image",
    ".png": "image",
}


def test_format_group_mapping() -> None:
    """Fixture format groups match expected categories."""
    from benchmark.fixtures import format_group_for_ext

    for ext, expected_group in FORMAT_GROUP_MAP.items():
        assert format_group_for_ext(ext) == expected_group, f"Wrong group for {ext}"
