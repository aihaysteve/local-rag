"""Pure git subprocess helpers for the git indexer.

All functions are pure — they take a repo_path and optional arguments,
execute git CLI commands, and return results. No class state dependency.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CommitInfo:
    """Parsed git commit metadata."""

    sha: str
    author_name: str
    author_email: str
    author_date: str
    subject: str


@dataclass
class FileChange:
    """A single file change from a git commit."""

    file_path: str
    additions: int
    deletions: int
    is_binary: bool


def run_git(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in the given repo directory.

    Args:
        repo_path: Path to the git repository.
        *args: Git subcommand and arguments.

    Returns:
        CompletedProcess result.

    Raises:
        subprocess.CalledProcessError: If the git command fails.
    """
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def is_git_repo(repo_path: Path) -> bool:
    """Check if a path is inside a git repository."""
    try:
        run_git(repo_path, "rev-parse", "--git-dir")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_head_sha(repo_path: Path) -> str:
    """Get the current HEAD commit SHA."""
    result = run_git(repo_path, "rev-parse", "HEAD")
    return result.stdout.strip()


def git_ls_files(repo_path: Path) -> list[str]:
    """List all tracked files in the repo."""
    result = run_git(repo_path, "ls-files")
    return [line for line in result.stdout.strip().split("\n") if line]


def git_diff_names(repo_path: Path, from_sha: str, to_sha: str = "HEAD") -> list[str]:
    """Get list of files changed between two commits."""
    result = run_git(repo_path, "diff", "--name-only", f"{from_sha}..{to_sha}")
    return [line for line in result.stdout.strip().split("\n") if line]


def commit_exists(repo_path: Path, sha: str) -> bool:
    """Check if a commit SHA exists in the repo."""
    try:
        run_git(repo_path, "cat-file", "-t", sha)
        return True
    except subprocess.CalledProcessError:
        return False


def get_commits_since(repo_path: Path, since_sha: str | None, months: int) -> list[CommitInfo]:
    """Get commits since a given SHA or within the last N months.

    Args:
        repo_path: Path to the git repository.
        since_sha: If set, only return commits after this SHA.
        months: How many months of history to include.

    Returns:
        List of CommitInfo, oldest first.
    """
    args = [
        "log",
        "--no-merges",
        f"--since={months} months ago",
        "--pretty=format:%H|%an|%ae|%aI|%s",
    ]
    if since_sha:
        args.append(f"{since_sha}..HEAD")

    try:
        result = run_git(repo_path, *args)
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to get commit log: %s", e)
        return []

    commits: list[CommitInfo] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 4)
        if len(parts) != 5:
            logger.debug("Skipping malformed log line: %s", line)
            continue
        commits.append(
            CommitInfo(
                sha=parts[0],
                author_name=parts[1],
                author_email=parts[2],
                author_date=parts[3],
                subject=parts[4],
            )
        )

    # Reverse so oldest commit is first (git log returns newest first)
    commits.reverse()
    return commits


def get_commit_file_changes(repo_path: Path, commit_sha: str) -> list[FileChange]:
    """Get the list of files changed in a commit with addition/deletion stats.

    Args:
        repo_path: Path to the git repository.
        commit_sha: The commit SHA to inspect.

    Returns:
        List of FileChange objects.
    """
    try:
        result = run_git(repo_path, "show", "--numstat", "--format=", commit_sha)
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to get file changes for %s: %s", commit_sha[:12], e)
        return []

    changes: list[FileChange] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        adds_str, dels_str, file_path = parts
        # Binary files show as "-\t-\tfilename"
        is_binary = adds_str == "-" and dels_str == "-"
        changes.append(
            FileChange(
                file_path=file_path,
                additions=0 if is_binary else int(adds_str),
                deletions=0 if is_binary else int(dels_str),
                is_binary=is_binary,
            )
        )
    return changes


def get_file_diff(repo_path: Path, commit_sha: str, file_path: str) -> str:
    """Get the diff for a specific file in a commit.

    Args:
        repo_path: Path to the git repository.
        commit_sha: The commit SHA.
        file_path: Path of the file within the repo.

    Returns:
        Raw diff text, or empty string on failure.
    """
    try:
        result = run_git(repo_path, "show", commit_sha, "--", file_path)
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to get diff for %s in %s: %s", file_path, commit_sha[:12], e)
        return ""
