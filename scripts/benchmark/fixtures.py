"""Fixture discovery and git repo generation for benchmarks."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Map extensions to format groups for the output table
_FORMAT_GROUPS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "office",
    ".pptx": "office",
    ".xlsx": "office",
    ".html": "office",
    ".htm": "office",
    ".md": "lightweight",
    ".txt": "lightweight",
    ".epub": "lightweight",
    ".json": "lightweight",
    ".yaml": "lightweight",
    ".yml": "lightweight",
    ".csv": "lightweight",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".ogg": "audio",
    ".flac": "audio",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".webp": "image",
}


def format_group_for_ext(ext: str) -> str:
    """Map a file extension to its benchmark format group."""
    return _FORMAT_GROUPS.get(ext.lower(), "other")


@dataclass
class Fixture:
    """A discovered benchmark fixture file."""

    path: Path
    name: str
    format_group: str
    file_size: int


def discover_fixtures(fixtures_dir: Path) -> list[Fixture]:
    """Discover fixture files in the given directory (top-level only).

    Args:
        fixtures_dir: Directory containing fixture files.

    Returns:
        List of Fixture objects sorted by name.
    """
    fixtures: list[Fixture] = []
    for item in sorted(fixtures_dir.iterdir()):
        if not item.is_file():
            continue
        ext = item.suffix.lower()
        group = format_group_for_ext(ext)
        fixtures.append(
            Fixture(
                path=item,
                name=item.name,
                format_group=group,
                file_size=item.stat().st_size,
            )
        )
    return fixtures


def _run_git(repo_dir: Path, *args: str) -> None:
    """Run a git command in a repo directory."""
    subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )


def generate_git_fixtures(fixtures_dir: Path) -> None:
    """Generate deterministic git repos for benchmarking.

    Creates git-repo-small (~10 Python files, few commits) and
    git-repo-large (~100+ mixed-language files, deeper history).
    Skips if repos already exist.

    Args:
        fixtures_dir: Directory to create repos in.
    """
    _generate_small_repo(fixtures_dir / "git-repo-small")
    _generate_large_repo(fixtures_dir / "git-repo-large")


def _generate_small_repo(repo_dir: Path) -> None:
    """Generate a small git repo (~10 Python files, 3 commits)."""
    if (repo_dir / ".git").exists():
        return

    repo_dir.mkdir(parents=True, exist_ok=True)
    _run_git(repo_dir, "init")
    _run_git(repo_dir, "config", "user.email", "bench@test.local")
    _run_git(repo_dir, "config", "user.name", "Benchmark")

    # Commit 1: initial files
    for i in range(10):
        (repo_dir / f"module_{i}.py").write_text(
            f'"""Module {i} for benchmark testing."""\n\n'
            f"def function_{i}(x: int) -> int:\n"
            f'    """Process value x in module {i}."""\n'
            f"    return x + {i}\n"
        )
    _run_git(repo_dir, "add", ".")
    _run_git(repo_dir, "commit", "-m", "Initial commit: 10 Python modules")

    # Commit 2: modify a few files
    for i in range(3):
        (repo_dir / f"module_{i}.py").write_text(
            f'"""Module {i} for benchmark testing (updated)."""\n\n'
            f"def function_{i}(x: int) -> int:\n"
            f'    """Process value x in module {i}."""\n'
            f"    result = x + {i}\n"
            f"    return result * 2\n"
        )
    _run_git(repo_dir, "add", ".")
    _run_git(repo_dir, "commit", "-m", "Update modules 0-2 with new logic")

    # Commit 3: add a README
    (repo_dir / "README.md").write_text("# Small Benchmark Repo\n\nTest repository.\n")
    _run_git(repo_dir, "add", ".")
    _run_git(repo_dir, "commit", "-m", "Add README")


def _generate_large_repo(repo_dir: Path) -> None:
    """Generate a large git repo (~100+ files, 5 commits, mixed languages)."""
    if (repo_dir / ".git").exists():
        return

    repo_dir.mkdir(parents=True, exist_ok=True)
    _run_git(repo_dir, "init")
    _run_git(repo_dir, "config", "user.email", "bench@test.local")
    _run_git(repo_dir, "config", "user.name", "Benchmark")

    # Create directory structure
    for subdir in ["src", "lib", "tests", "docs", "config"]:
        (repo_dir / subdir).mkdir(exist_ok=True)

    # Commit 1: Python files
    for i in range(40):
        d = "src" if i < 20 else "lib"
        (repo_dir / d / f"module_{i}.py").write_text(
            f'"""Module {i}."""\n\n'
            f"class Handler{i}:\n"
            f'    """Handler for operation {i}."""\n\n'
            f"    def process(self, data: list[int]) -> list[int]:\n"
            f"        return [x + {i} for x in data]\n\n"
            f"    def validate(self, value: int) -> bool:\n"
            f"        return value >= 0\n"
        )
    _run_git(repo_dir, "add", ".")
    _run_git(repo_dir, "commit", "-m", "Initial commit: Python modules")

    # Commit 2: JavaScript files
    for i in range(30):
        (repo_dir / "src" / f"component_{i}.js").write_text(
            f"// Component {i}\n"
            f"export function component{i}(props) {{\n"
            f"  const value = props.value + {i};\n"
            f"  return {{ value, label: `Item {i}` }};\n"
            f"}}\n"
        )
    _run_git(repo_dir, "add", ".")
    _run_git(repo_dir, "commit", "-m", "Add JavaScript components")

    # Commit 3: Go files
    for i in range(20):
        (repo_dir / "lib" / f"handler_{i}.go").write_text(
            f"package lib\n\n"
            f"// Handler{i} processes data.\n"
            f"func Handler{i}(input int) int {{\n"
            f"\treturn input + {i}\n"
            f"}}\n"
        )
    _run_git(repo_dir, "add", ".")
    _run_git(repo_dir, "commit", "-m", "Add Go handlers")

    # Commit 4: Test files
    for i in range(20):
        (repo_dir / "tests" / f"test_module_{i}.py").write_text(
            f'"""Tests for module {i}."""\n\n'
            f"def test_handler_{i}():\n"
            f"    from src.module_{i} import Handler{i}\n"
            f"    h = Handler{i}()\n"
            f"    assert h.process([1, 2, 3]) == [{1 + i}, {2 + i}, {3 + i}]\n"
        )
    _run_git(repo_dir, "add", ".")
    _run_git(repo_dir, "commit", "-m", "Add test suite")

    # Commit 5: Docs and config
    (repo_dir / "docs" / "README.md").write_text(
        "# Large Benchmark Repo\n\nMulti-language test repository.\n"
    )
    (repo_dir / "config" / "settings.yaml").write_text("debug: false\nlog_level: info\n")
    _run_git(repo_dir, "add", ".")
    _run_git(repo_dir, "commit", "-m", "Add documentation and config")
