"""Tests for indexers.git_commands — pure git subprocess helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a git repo with one committed file."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "T"],
        capture_output=True,
        check=True,
    )
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "."],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"],
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "T",
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "T",
            "GIT_COMMITTER_EMAIL": "t@t.com",
        },
    )
    return tmp_path


class TestImports:
    """git_commands exports are importable."""

    def test_run_git_importable(self) -> None:
        from ragling.indexers.git_commands import run_git

        assert callable(run_git)

    def test_is_git_repo_importable(self) -> None:
        from ragling.indexers.git_commands import is_git_repo

        assert callable(is_git_repo)

    def test_get_head_sha_importable(self) -> None:
        from ragling.indexers.git_commands import get_head_sha

        assert callable(get_head_sha)

    def test_commit_info_importable(self) -> None:
        from ragling.indexers.git_commands import CommitInfo

        assert CommitInfo is not None

    def test_file_change_importable(self) -> None:
        from ragling.indexers.git_commands import FileChange

        assert FileChange is not None

    def test_git_ls_files_importable(self) -> None:
        from ragling.indexers.git_commands import git_ls_files

        assert callable(git_ls_files)

    def test_git_diff_names_importable(self) -> None:
        from ragling.indexers.git_commands import git_diff_names

        assert callable(git_diff_names)

    def test_commit_exists_importable(self) -> None:
        from ragling.indexers.git_commands import commit_exists

        assert callable(commit_exists)

    def test_get_commits_since_importable(self) -> None:
        from ragling.indexers.git_commands import get_commits_since

        assert callable(get_commits_since)

    def test_get_commit_file_changes_importable(self) -> None:
        from ragling.indexers.git_commands import get_commit_file_changes

        assert callable(get_commit_file_changes)

    def test_get_file_diff_importable(self) -> None:
        from ragling.indexers.git_commands import get_file_diff

        assert callable(get_file_diff)


class TestIsGitRepo:
    """is_git_repo detects git repositories."""

    def test_non_git_dir_returns_false(self, tmp_path: Path) -> None:
        from ragling.indexers.git_commands import is_git_repo

        assert is_git_repo(tmp_path) is False

    def test_git_dir_returns_true(self, git_repo: Path) -> None:
        from ragling.indexers.git_commands import is_git_repo

        assert is_git_repo(git_repo) is True


class TestRunGit:
    """run_git executes git commands in repo context."""

    def test_returns_completed_process(self, git_repo: Path) -> None:
        from ragling.indexers.git_commands import run_git

        result = run_git(git_repo, "status")
        assert result.returncode == 0

    def test_raises_on_bad_command(self, git_repo: Path) -> None:
        from ragling.indexers.git_commands import run_git

        with pytest.raises(subprocess.CalledProcessError):
            run_git(git_repo, "not-a-real-command")


class TestGetHeadSha:
    """get_head_sha returns HEAD commit SHA."""

    def test_returns_sha_string(self, git_repo: Path) -> None:
        from ragling.indexers.git_commands import get_head_sha

        sha = get_head_sha(git_repo)
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)


class TestGitLsFiles:
    """git_ls_files returns tracked file list."""

    def test_returns_tracked_files(self, git_repo: Path) -> None:
        from ragling.indexers.git_commands import git_ls_files

        # Add a second file
        (git_repo / "a.py").write_text("pass")
        subprocess.run(
            ["git", "-C", str(git_repo), "add", "a.py"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-m", "add a"],
            capture_output=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "T",
                "GIT_AUTHOR_EMAIL": "t@t.com",
                "GIT_COMMITTER_NAME": "T",
                "GIT_COMMITTER_EMAIL": "t@t.com",
            },
        )

        files = git_ls_files(git_repo)
        assert "f.txt" in files
        assert "a.py" in files


class TestCommitExists:
    """commit_exists checks if a SHA exists."""

    def test_existing_commit_returns_true(self, git_repo: Path) -> None:
        from ragling.indexers.git_commands import commit_exists, get_head_sha

        sha = get_head_sha(git_repo)
        assert commit_exists(git_repo, sha) is True

    def test_nonexistent_commit_returns_false(self, git_repo: Path) -> None:
        from ragling.indexers.git_commands import commit_exists

        assert commit_exists(git_repo, "deadbeef" * 5) is False


class TestCommitInfo:
    """CommitInfo dataclass holds commit metadata."""

    def test_fields(self) -> None:
        from ragling.indexers.git_commands import CommitInfo

        ci = CommitInfo(
            sha="abc123",
            author_name="Alice",
            author_email="alice@example.com",
            author_date="2025-01-01T00:00:00+00:00",
            subject="init commit",
        )
        assert ci.sha == "abc123"
        assert ci.author_name == "Alice"
        assert ci.author_email == "alice@example.com"
        assert ci.subject == "init commit"


class TestFileChange:
    """FileChange dataclass holds file change metadata."""

    def test_fields(self) -> None:
        from ragling.indexers.git_commands import FileChange

        fc = FileChange(
            file_path="src/main.py",
            additions=10,
            deletions=2,
            is_binary=False,
        )
        assert fc.file_path == "src/main.py"
        assert fc.additions == 10
        assert fc.deletions == 2
        assert fc.is_binary is False
