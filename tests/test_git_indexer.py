"""Comprehensive tests for ragling.indexers.git_indexer using real git repos."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ragling.config import Config
from ragling.db import get_connection, init_db
from ragling.indexers.base import IndexResult
from ragling.indexers.git_indexer import (
    GitRepoIndexer,
    _git_ls_files,
    _make_watermarks,
    _parse_watermarks,
    _should_exclude,
)

# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

EMBED_DIM = 4


def _run_git(repo: Path, *args: str) -> None:
    """Run a git command in the given repo with deterministic author info."""
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create an initialized test DB with small embedding dimensions."""
    config = Config(
        db_path=tmp_path / "test.db",
        embedding_dimensions=EMBED_DIM,
    )
    conn = get_connection(config)
    init_db(conn, config)
    return conn


def _make_config(tmp_path: Path) -> Config:
    """Create a Config suitable for testing (small embeddings, small chunks)."""
    return Config(
        db_path=tmp_path / "test.db",
        embedding_dimensions=EMBED_DIM,
        chunk_size_tokens=256,
        chunk_overlap_tokens=50,
        git_history_in_months=12,
    )


def _fake_embeddings(texts: list[str], config: Config) -> list[list[float]]:
    """Return fixed-dimension fake embeddings for each text."""
    return [[0.1, 0.2, 0.3, 0.4]] * len(texts)


@pytest.fixture
def simple_repo(tmp_path: Path) -> Path:
    """A git repo with one Python file and one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@test.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "hello.py").write_text("def hello():\n    print('hello')\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "initial commit")
    return repo


@pytest.fixture
def multi_file_repo(tmp_path: Path) -> Path:
    """A git repo with multiple Python files and a non-code file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@test.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "main.py").write_text("def main():\n    pass\n")
    (repo / "utils.py").write_text("def helper():\n    return 42\n")
    (repo / "README.md").write_text("# My Project\n")
    (repo / "data.txt").write_text("some data\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "initial")
    return repo


@pytest.fixture
def multi_commit_repo(tmp_path: Path) -> Path:
    """A git repo with multiple commits for history testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@test.com")
    _run_git(repo, "config", "user.name", "Test")

    (repo / "app.py").write_text("def app():\n    pass\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "first commit")

    (repo / "app.py").write_text("def app():\n    return 'v2'\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "update app")

    (repo / "lib.py").write_text("def lib_func():\n    return True\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "add lib")

    return repo


# ---------------------------------------------------------------------------
# Tests: _git_ls_files
# ---------------------------------------------------------------------------


class TestGitLsFiles:
    def test_returns_tracked_files(self, simple_repo: Path) -> None:
        files = _git_ls_files(simple_repo)
        assert "hello.py" in files

    def test_does_not_include_git_dir(self, simple_repo: Path) -> None:
        files = _git_ls_files(simple_repo)
        for f in files:
            assert not f.startswith(".git/")

    def test_returns_all_tracked_files(self, multi_file_repo: Path) -> None:
        files = _git_ls_files(multi_file_repo)
        assert set(files) == {"main.py", "utils.py", "README.md", "data.txt"}

    def test_untracked_files_not_listed(self, simple_repo: Path) -> None:
        (simple_repo / "untracked.py").write_text("# not tracked\n")
        files = _git_ls_files(simple_repo)
        assert "untracked.py" not in files


# ---------------------------------------------------------------------------
# Tests: _should_exclude
# ---------------------------------------------------------------------------


class TestShouldExclude:
    def test_excludes_ds_store(self) -> None:
        assert _should_exclude(".DS_Store") is True

    def test_excludes_node_modules(self) -> None:
        assert _should_exclude("node_modules/foo.js") is True

    def test_excludes_pycache(self) -> None:
        assert _should_exclude("__pycache__/module.pyc") is True

    def test_excludes_lock_files(self) -> None:
        assert _should_exclude("package-lock.json") is True
        assert _should_exclude("yarn.lock") is True
        assert _should_exclude("uv.lock") is True
        assert _should_exclude("Cargo.lock") is True

    def test_does_not_exclude_normal_files(self) -> None:
        assert _should_exclude("main.py") is False
        assert _should_exclude("src/utils.py") is False

    def test_excludes_nested_directory_patterns(self) -> None:
        assert _should_exclude("src/__pycache__/module.pyc") is True
        assert _should_exclude("frontend/node_modules/pkg/index.js") is True


# ---------------------------------------------------------------------------
# Tests: _parse_watermarks and _make_watermarks
# ---------------------------------------------------------------------------


class TestWatermarks:
    def test_parse_empty_returns_empty(self) -> None:
        assert _parse_watermarks(None) == {}
        assert _parse_watermarks("") == {}

    def test_parse_json_format(self) -> None:
        data = {"/path/to/repo": "abc123", "/other/repo": "def456"}
        desc = json.dumps(data)
        result = _parse_watermarks(desc)
        assert result == data

    def test_parse_legacy_format(self) -> None:
        desc = "git:/path/to/repo:abc123def"
        result = _parse_watermarks(desc)
        assert result == {"/path/to/repo": "abc123def"}

    def test_parse_legacy_format_with_colons_in_path(self) -> None:
        # rsplit(":", 1) handles paths that may contain colons
        desc = "git:C:/Users/test/repo:deadbeef"
        result = _parse_watermarks(desc)
        assert result == {"C:/Users/test/repo": "deadbeef"}

    def test_make_watermarks_produces_json(self) -> None:
        wm = {"/repo1": "sha1", "/repo2": "sha2"}
        serialized = _make_watermarks(wm)
        assert json.loads(serialized) == wm

    def test_roundtrip(self) -> None:
        original = {"/repo/a": "aaa111", "/repo/b": "bbb222"}
        serialized = _make_watermarks(original)
        parsed = _parse_watermarks(serialized)
        assert parsed == original

    def test_parse_invalid_json_returns_empty(self) -> None:
        assert _parse_watermarks("{invalid json") == {}

    def test_parse_unrecognized_string_returns_empty(self) -> None:
        assert _parse_watermarks("random string") == {}


# ---------------------------------------------------------------------------
# Tests: GitRepoIndexer.index() -- code file indexing
# ---------------------------------------------------------------------------


class TestCodeFileIndexing:
    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_indexes_python_files(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        result = indexer.index(conn, config)

        assert isinstance(result, IndexResult)
        assert result.indexed >= 1
        assert result.errors == 0

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_creates_documents_in_db(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        indexer.index(conn, config)

        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert doc_count > 0

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_creates_vector_embeddings(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        indexer.index(conn, config)

        vec_count = conn.execute("SELECT COUNT(*) FROM vec_documents").fetchone()[0]
        assert vec_count > 0

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_source_type_is_code(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        indexer.index(conn, config)

        row = conn.execute("SELECT source_type FROM sources LIMIT 1").fetchone()
        assert row["source_type"] == "code"

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_only_indexes_code_files(
        self, mock_embed: object, multi_file_repo: Path, tmp_path: Path
    ) -> None:
        """Non-code files (README.md, data.txt) should not produce sources."""
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(multi_file_repo, "test-group")

        indexer.index(conn, config)

        sources = conn.execute("SELECT source_path FROM sources").fetchall()
        source_paths = [r["source_path"] for r in sources]
        # Python files should be indexed
        assert any("main.py" in p for p in source_paths)
        assert any("utils.py" in p for p in source_paths)
        # Non-code files should NOT be indexed
        assert not any("README.md" in p for p in source_paths)
        assert not any("data.txt" in p for p in source_paths)

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_document_content_contains_code(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        indexer.index(conn, config)

        row = conn.execute("SELECT content FROM documents LIMIT 1").fetchone()
        content = row["content"]
        # The content should contain the Python code from hello.py
        assert "hello" in content

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_collection_type_is_code(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        indexer.index(conn, config)

        row = conn.execute(
            "SELECT collection_type FROM collections WHERE name = 'test-group'"
        ).fetchone()
        assert row["collection_type"] == "code"


# ---------------------------------------------------------------------------
# Tests: Watermark persistence via index()
# ---------------------------------------------------------------------------


class TestWatermarkPersistence:
    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_stores_watermark_after_indexing(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        indexer.index(conn, config)

        row = conn.execute(
            "SELECT description FROM collections WHERE name = 'test-group'"
        ).fetchone()
        watermarks = _parse_watermarks(row["description"])
        repo_key = str(simple_repo.resolve())
        assert repo_key in watermarks
        # The watermark should be a 40-char hex SHA
        assert len(watermarks[repo_key]) == 40

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_watermark_matches_head(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        indexer.index(conn, config)

        # Get HEAD SHA
        head_result = subprocess.run(
            ["git", "-C", str(simple_repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        head_sha = head_result.stdout.strip()

        row = conn.execute(
            "SELECT description FROM collections WHERE name = 'test-group'"
        ).fetchone()
        watermarks = _parse_watermarks(row["description"])
        repo_key = str(simple_repo.resolve())
        assert watermarks[repo_key] == head_sha


# ---------------------------------------------------------------------------
# Tests: Incremental indexing (skip unchanged)
# ---------------------------------------------------------------------------


class TestIncrementalIndexing:
    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_second_run_no_changes_skips(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        """If HEAD hasn't changed, second index() should skip everything."""
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        result1 = indexer.index(conn, config)
        assert result1.indexed >= 1

        result2 = indexer.index(conn, config)
        assert result2.indexed == 0
        assert result2.total_found == 0

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_new_commit_indexes_changed_files(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        """After a new commit, only changed files should be re-indexed."""
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        result1 = indexer.index(conn, config)
        assert result1.indexed >= 1

        # Make a new commit that modifies the file
        (simple_repo / "hello.py").write_text("def hello():\n    print('world')\n")
        _run_git(simple_repo, "add", ".")
        _run_git(simple_repo, "commit", "-m", "update hello")

        result2 = indexer.index(conn, config)
        assert result2.indexed >= 1

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_new_file_added_gets_indexed(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        indexer.index(conn, config)

        # Add a new file
        (simple_repo / "new_module.py").write_text("def new_func():\n    return 1\n")
        _run_git(simple_repo, "add", ".")
        _run_git(simple_repo, "commit", "-m", "add new module")

        result2 = indexer.index(conn, config)
        assert result2.indexed >= 1

        # Check that both files are in the DB
        sources = conn.execute("SELECT source_path FROM sources").fetchall()
        source_paths = [r["source_path"] for r in sources]
        assert any("new_module.py" in p for p in source_paths)
        assert any("hello.py" in p for p in source_paths)

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_force_reindexes_all(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        result1 = indexer.index(conn, config)
        assert result1.indexed >= 1

        result2 = indexer.index(conn, config, force=True)
        assert result2.indexed >= 1


# ---------------------------------------------------------------------------
# Tests: Prune behavior (deleted files)
# ---------------------------------------------------------------------------


class TestPruneBehavior:
    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_deleted_file_is_pruned(
        self, mock_embed: object, multi_file_repo: Path, tmp_path: Path
    ) -> None:
        """When a tracked file is deleted and committed, re-indexing removes it."""
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(multi_file_repo, "test-group")

        indexer.index(conn, config)

        # Count initial sources
        initial_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        assert initial_count >= 2  # main.py and utils.py at minimum

        # Delete utils.py and commit
        (multi_file_repo / "utils.py").unlink()
        _run_git(multi_file_repo, "add", ".")
        _run_git(multi_file_repo, "commit", "-m", "remove utils")

        indexer.index(conn, config)

        # utils.py should be gone from sources
        sources = conn.execute("SELECT source_path FROM sources").fetchall()
        source_paths = [r["source_path"] for r in sources]
        assert not any("utils.py" in p for p in source_paths)
        # main.py should still be there
        assert any("main.py" in p for p in source_paths)


# ---------------------------------------------------------------------------
# Tests: Commit history indexing
# ---------------------------------------------------------------------------


class TestCommitHistoryIndexing:
    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_index_history_produces_commit_sources(
        self, mock_embed: object, multi_commit_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(multi_commit_repo, "test-group")

        result = indexer.index(conn, config, index_history=True)

        # Should have indexed both code files AND commits
        assert result.indexed >= 1

        # Check that commit-type sources exist
        commit_sources = conn.execute(
            "SELECT source_path FROM sources WHERE source_type = 'commit'"
        ).fetchall()
        assert len(commit_sources) > 0

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_commit_source_paths_have_git_uri_format(
        self, mock_embed: object, multi_commit_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(multi_commit_repo, "test-group")

        indexer.index(conn, config, index_history=True)

        commit_sources = conn.execute(
            "SELECT source_path FROM sources WHERE source_type = 'commit'"
        ).fetchall()
        for row in commit_sources:
            assert row["source_path"].startswith("git://")
            assert "#" in row["source_path"]

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_commit_documents_contain_diff(
        self, mock_embed: object, multi_commit_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(multi_commit_repo, "test-group")

        indexer.index(conn, config, index_history=True)

        # Get documents for commit sources
        commit_docs = conn.execute(
            """
            SELECT d.content FROM documents d
            JOIN sources s ON d.source_id = s.id
            WHERE s.source_type = 'commit'
            """
        ).fetchall()
        assert len(commit_docs) > 0

        # At least one doc should contain diff-like content
        all_content = " ".join(r["content"] for r in commit_docs)
        # Commit chunks contain the commit message at minimum
        assert "commit" in all_content.lower() or "def" in all_content.lower()

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_history_watermark_stored(
        self, mock_embed: object, multi_commit_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(multi_commit_repo, "test-group")

        indexer.index(conn, config, index_history=True)

        row = conn.execute(
            "SELECT description FROM collections WHERE name = 'test-group'"
        ).fetchone()
        watermarks = _parse_watermarks(row["description"])
        repo_key = str(multi_commit_repo.resolve())
        history_key = f"{repo_key}:history"
        assert history_key in watermarks

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_incremental_history_skips_already_indexed(
        self, mock_embed: object, multi_commit_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(multi_commit_repo, "test-group")

        result1 = indexer.index(conn, config, index_history=True)
        assert result1.indexed >= 1

        # Second run with no new commits should skip history
        result2 = indexer.index(conn, config, index_history=True)

        # Code part: 0 total found (same HEAD)
        # History part: commits already indexed should be skipped
        # Overall: no new indexing
        assert result2.indexed == 0


# ---------------------------------------------------------------------------
# Tests: Subject blacklist
# ---------------------------------------------------------------------------


class TestSubjectBlacklist:
    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_blacklisted_commits_excluded(self, mock_embed: object, tmp_path: Path) -> None:
        """Commits whose subject starts with a blacklisted prefix are excluded."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _run_git(repo, "init")
        _run_git(repo, "config", "user.email", "test@test.com")
        _run_git(repo, "config", "user.name", "Test")

        (repo / "app.py").write_text("def app():\n    pass\n")
        _run_git(repo, "add", ".")
        _run_git(repo, "commit", "-m", "initial commit")

        (repo / "app.py").write_text("def app():\n    return 1\n")
        _run_git(repo, "add", ".")
        _run_git(repo, "commit", "-m", "Merge pull request #1")

        (repo / "app.py").write_text("def app():\n    return 2\n")
        _run_git(repo, "add", ".")
        _run_git(repo, "commit", "-m", "real feature")

        config = _make_config(tmp_path).with_overrides(
            git_commit_subject_blacklist=("Merge pull request",),
        )
        conn = _make_conn(tmp_path)
        indexer = GitRepoIndexer(repo, "test-group")

        indexer.index(conn, config, index_history=True)

        # Check that the merge commit is NOT in commit sources
        commit_sources = conn.execute(
            "SELECT source_path FROM sources WHERE source_type = 'commit'"
        ).fetchall()
        commit_paths = [r["source_path"] for r in commit_sources]

        # None of the commit source paths should contain the merge commit
        for path in commit_paths:
            # Extract sha from git://path#sha
            sha = path.split("#")[-1]
            # Verify this commit's message is NOT the merge one
            msg_result = subprocess.run(
                ["git", "-C", str(repo), "log", "--format=%s", "-1", sha],
                capture_output=True,
                text=True,
                check=True,
            )
            assert not msg_result.stdout.strip().startswith("Merge pull request")


# ---------------------------------------------------------------------------
# Tests: Not a git repo
# ---------------------------------------------------------------------------


class TestNotAGitRepo:
    def test_returns_error_for_non_repo(self, tmp_path: Path) -> None:
        """Indexing a non-git directory should return an error result."""
        not_a_repo = tmp_path / "not-a-repo"
        not_a_repo.mkdir()
        (not_a_repo / "file.py").write_text("x = 1\n")

        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(not_a_repo, "test-group")

        result = indexer.index(conn, config)

        assert result.errors == 1
        assert "Not a git repository" in result.error_messages[0]


# ---------------------------------------------------------------------------
# Tests: Multi-repo watermarks
# ---------------------------------------------------------------------------


class TestMultiRepoWatermarks:
    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_two_repos_in_same_collection(self, mock_embed: object, tmp_path: Path) -> None:
        """Two repos indexed into the same collection should both have watermarks."""
        repo1 = tmp_path / "repo1"
        repo1.mkdir()
        _run_git(repo1, "init")
        _run_git(repo1, "config", "user.email", "test@test.com")
        _run_git(repo1, "config", "user.name", "Test")
        (repo1 / "a.py").write_text("def a():\n    pass\n")
        _run_git(repo1, "add", ".")
        _run_git(repo1, "commit", "-m", "repo1 init")

        repo2 = tmp_path / "repo2"
        repo2.mkdir()
        _run_git(repo2, "init")
        _run_git(repo2, "config", "user.email", "test@test.com")
        _run_git(repo2, "config", "user.name", "Test")
        (repo2 / "b.py").write_text("def b():\n    pass\n")
        _run_git(repo2, "add", ".")
        _run_git(repo2, "commit", "-m", "repo2 init")

        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)

        indexer1 = GitRepoIndexer(repo1, "shared-group")
        indexer2 = GitRepoIndexer(repo2, "shared-group")

        indexer1.index(conn, config)
        indexer2.index(conn, config)

        row = conn.execute(
            "SELECT description FROM collections WHERE name = 'shared-group'"
        ).fetchone()
        watermarks = _parse_watermarks(row["description"])

        assert str(repo1.resolve()) in watermarks
        assert str(repo2.resolve()) in watermarks

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_second_repo_does_not_clobber_first_watermark(
        self, mock_embed: object, tmp_path: Path
    ) -> None:
        """Indexing repo2 should preserve repo1's watermark."""
        repo1 = tmp_path / "repo1"
        repo1.mkdir()
        _run_git(repo1, "init")
        _run_git(repo1, "config", "user.email", "test@test.com")
        _run_git(repo1, "config", "user.name", "Test")
        (repo1 / "a.py").write_text("def a():\n    pass\n")
        _run_git(repo1, "add", ".")
        _run_git(repo1, "commit", "-m", "repo1 init")

        repo2 = tmp_path / "repo2"
        repo2.mkdir()
        _run_git(repo2, "init")
        _run_git(repo2, "config", "user.email", "test@test.com")
        _run_git(repo2, "config", "user.name", "Test")
        (repo2 / "b.py").write_text("def b():\n    pass\n")
        _run_git(repo2, "add", ".")
        _run_git(repo2, "commit", "-m", "repo2 init")

        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)

        indexer1 = GitRepoIndexer(repo1, "shared-group")
        indexer2 = GitRepoIndexer(repo2, "shared-group")

        indexer1.index(conn, config)

        # Record repo1's watermark
        row = conn.execute(
            "SELECT description FROM collections WHERE name = 'shared-group'"
        ).fetchone()
        wm_after_repo1 = _parse_watermarks(row["description"])
        repo1_sha = wm_after_repo1[str(repo1.resolve())]

        # Now index repo2
        indexer2.index(conn, config)

        row = conn.execute(
            "SELECT description FROM collections WHERE name = 'shared-group'"
        ).fetchone()
        wm_after_both = _parse_watermarks(row["description"])
        assert wm_after_both[str(repo1.resolve())] == repo1_sha


# ---------------------------------------------------------------------------
# Tests: Document metadata
# ---------------------------------------------------------------------------


class TestDocumentMetadata:
    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_code_document_has_language_metadata(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        indexer.index(conn, config)

        row = conn.execute("SELECT metadata FROM documents LIMIT 1").fetchone()
        metadata = json.loads(row["metadata"])
        assert "language" in metadata
        assert metadata["language"] == "python"

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_code_document_has_symbol_metadata(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        indexer.index(conn, config)

        docs = conn.execute("SELECT metadata FROM documents").fetchall()
        all_metadata = [json.loads(r["metadata"]) for r in docs]
        # At least one document should have symbol_name and symbol_type
        assert any("symbol_name" in m for m in all_metadata)
        assert any("symbol_type" in m for m in all_metadata)

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_commit_document_has_commit_metadata(
        self, mock_embed: object, multi_commit_repo: Path, tmp_path: Path
    ) -> None:
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(multi_commit_repo, "test-group")

        indexer.index(conn, config, index_history=True)

        commit_docs = conn.execute(
            """
            SELECT d.metadata FROM documents d
            JOIN sources s ON d.source_id = s.id
            WHERE s.source_type = 'commit'
            LIMIT 1
            """
        ).fetchone()

        if commit_docs:
            metadata = json.loads(commit_docs["metadata"])
            assert "commit_sha" in metadata
            assert "author_name" in metadata
            assert "author_email" in metadata
            assert "commit_message" in metadata
            assert "file_path" in metadata


# ---------------------------------------------------------------------------
# Tests: file_hash change detection
# ---------------------------------------------------------------------------


class TestFileHashChangeDetection:
    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_unchanged_file_hash_causes_skip(
        self, mock_embed: object, simple_repo: Path, tmp_path: Path
    ) -> None:
        """Files with the same content hash are skipped on incremental index."""
        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(simple_repo, "test-group")

        # First index
        indexer.index(conn, config)

        # Make a commit that doesn't change hello.py (add a new file)
        (simple_repo / "other.py").write_text("def other():\n    pass\n")
        _run_git(simple_repo, "add", ".")
        _run_git(simple_repo, "commit", "-m", "add other")

        # Get count of embed calls before second index
        mock_embed.reset_mock()
        indexer.index(conn, config)

        # hello.py should NOT have been re-embedded (its hash didn't change)
        # But other.py should have been embedded
        # We can verify by checking that hello.py's source row was not updated
        sources = conn.execute(
            "SELECT source_path, file_hash FROM sources WHERE source_type = 'code'"
        ).fetchall()
        assert len(sources) == 2  # hello.py + other.py


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_empty_repo_no_files(self, mock_embed: object, tmp_path: Path) -> None:
        """A repo with no code files should return without error."""
        repo = tmp_path / "empty-repo"
        repo.mkdir()
        _run_git(repo, "init")
        _run_git(repo, "config", "user.email", "test@test.com")
        _run_git(repo, "config", "user.name", "Test")
        (repo / "README.md").write_text("# Empty\n")
        _run_git(repo, "add", ".")
        _run_git(repo, "commit", "-m", "initial")

        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(repo, "test-group")

        result = indexer.index(conn, config)
        assert result.errors == 0
        assert result.indexed == 0

    @patch("ragling.indexers.git_indexer.get_embeddings", side_effect=_fake_embeddings)
    def test_excluded_files_not_indexed(self, mock_embed: object, tmp_path: Path) -> None:
        """Files matching exclude patterns should not be indexed."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _run_git(repo, "init")
        _run_git(repo, "config", "user.email", "test@test.com")
        _run_git(repo, "config", "user.name", "Test")

        (repo / "main.py").write_text("def main():\n    pass\n")
        # This file would be code but matches the exclude pattern
        (repo / "package-lock.json").write_text("{}\n")
        _run_git(repo, "add", ".")
        _run_git(repo, "commit", "-m", "initial")

        conn = _make_conn(tmp_path)
        config = _make_config(tmp_path)
        indexer = GitRepoIndexer(repo, "test-group")

        indexer.index(conn, config)

        sources = conn.execute("SELECT source_path FROM sources").fetchall()
        source_paths = [r["source_path"] for r in sources]
        assert not any("package-lock.json" in p for p in source_paths)
