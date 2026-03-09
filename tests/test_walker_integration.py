"""Integration tests for the unified DFS walker pipeline.

Exercises the full walk -> process -> verify pipeline with real
directory structures containing git repos and Obsidian vaults.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ragling.document.chunker import Chunk
from ragling.indexers.walk_processor import process_walk_result
from ragling.indexers.walker import walk, assign_collection


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a workspace with a git repo containing a nested Obsidian vault.

    Structure:
        workspace/
        ├── .git/
        ├── SPEC.md
        ├── src/
        │   └── main.py
        ├── README.md
        └── notes/
            ├── .obsidian/
            ├── daily.md
            └── code_snippet.py
    """
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Git repo at root (just create .git dir, no real git needed)
    (ws / ".git").mkdir()

    # SPEC.md at root
    (ws / "SPEC.md").write_text("# MyProject\n\n## Purpose\n\nDoes things.\n")

    # Source code
    src = ws / "src"
    src.mkdir()
    (src / "main.py").write_text("def hello():\n    print('hello')\n")

    # README at repo root
    (ws / "README.md").write_text("# My Project\n\nA project.\n")

    # Obsidian vault nested inside
    notes = ws / "notes"
    notes.mkdir()
    (notes / ".obsidian").mkdir()
    (notes / "daily.md").write_text("# Daily Note\n\nToday I learned things.\n")
    (notes / "code_snippet.py").write_text("x = 42\n")

    return ws


class TestDuplicateIndexingRegression:
    """Regression test for issues #49 and #51.  # Tests INV-6"""

    def test_no_duplicate_files_across_collections(self, workspace: Path) -> None:
        """Each file should appear in exactly one collection."""
        walk_result = walk(workspace)

        # Assign collections for each route
        collections_per_file: dict[str, list[str]] = {}
        for route in walk_result.routes:
            coll = assign_collection(
                route, watch_name="workspace", watch_root=workspace
            )
            fname = route.path.name
            collections_per_file.setdefault(fname, []).append(coll)

        # No file should appear in more than one collection
        for fname, colls in collections_per_file.items():
            assert len(colls) == 1, (
                f"{fname} appears in multiple collections: {colls}"
            )

    def test_vault_files_in_vault_collection(self, workspace: Path) -> None:
        """Files inside the vault should be in the vault collection."""
        walk_result = walk(workspace)

        vault_files = []
        for route in walk_result.routes:
            coll = assign_collection(
                route, watch_name="workspace", watch_root=workspace
            )
            if coll == "workspace/notes":
                vault_files.append(route.path.name)

        assert "daily.md" in vault_files
        assert "code_snippet.py" in vault_files

    def test_repo_files_in_repo_collection(self, workspace: Path) -> None:
        """Files outside the vault should be in the repo/watch collection."""
        walk_result = walk(workspace)

        repo_files = []
        for route in walk_result.routes:
            coll = assign_collection(
                route, watch_name="workspace", watch_root=workspace
            )
            if coll == "workspace":
                repo_files.append(route.path.name)

        assert "main.py" in repo_files
        assert "README.md" in repo_files
        assert "SPEC.md" in repo_files

    def test_spec_md_uses_spec_parser(self, workspace: Path) -> None:
        """Tests INV-10: SPEC.md must go through spec parser."""
        walk_result = walk(workspace)

        spec_routes = [r for r in walk_result.routes if r.path.name == "SPEC.md"]
        assert len(spec_routes) == 1
        assert spec_routes[0].parser == "spec"

    def test_vault_context_propagates(self, workspace: Path) -> None:
        """Files in vault should have vault_root set."""
        walk_result = walk(workspace)

        for route in walk_result.routes:
            if "notes" in str(route.path):
                assert route.vault_root == workspace / "notes"
                assert route.git_root == workspace  # also in git repo

    def test_non_vault_files_have_no_vault_root(self, workspace: Path) -> None:
        """Files outside vault should have vault_root=None."""
        walk_result = walk(workspace)

        for route in walk_result.routes:
            if "notes" not in str(route.path):
                assert route.vault_root is None

    @patch("ragling.indexers.walk_processor.prune_stale_sources", return_value=0)
    @patch(
        "ragling.indexers.walk_processor.upsert_source_with_chunks", return_value=1
    )
    @patch("ragling.indexers.walk_processor.get_embeddings")
    @patch("ragling.indexers.walk_processor._parse_route")
    @patch("ragling.indexers.walk_processor.file_hash", return_value="fakehash123")
    @patch("ragling.indexers.walk_processor.get_or_create_collection")
    def test_process_dispatches_to_correct_collections(
        self,
        mock_get_coll: MagicMock,
        mock_hash: MagicMock,
        mock_parse: MagicMock,
        mock_embed: MagicMock,
        mock_upsert: MagicMock,
        mock_prune: MagicMock,
        workspace: Path,
    ) -> None:
        """Verify process_walk_result uses correct collection IDs."""
        # Setup mocks
        mock_get_coll.side_effect = lambda conn, name, **kw: hash(name) % 1000
        mock_parse.return_value = [
            Chunk(text="test content", title="test", metadata={}, chunk_index=0)
        ]
        mock_embed.return_value = [[0.1, 0.2, 0.3, 0.4]]

        walk_result = walk(workspace)

        # Use a mock conn since we can't use real sqlite-vec
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (
            None  # No existing source
        )

        config = MagicMock()
        process_walk_result(
            walk_result,
            mock_conn,
            config,
            watch_name="workspace",
            watch_root=workspace,
        )

        # Verify collections were created
        coll_names = {
            call_args[0][1] for call_args in mock_get_coll.call_args_list
        }
        assert "workspace" in coll_names  # for repo files
        assert "workspace/notes" in coll_names  # for vault files

        # Verify upsert was called for each routed file
        assert mock_upsert.call_count == len(walk_result.routes)
