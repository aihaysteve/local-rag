"""Tests for ragling.sync module."""

import threading
from pathlib import Path
from types import MappingProxyType
from unittest.mock import MagicMock, patch

from ragling.config import Config, UserConfig
from ragling.indexing_queue import IndexJob


class TestSyncMapFileToCollection:
    """Tests for mapping a file path to its collection name."""

    def test_file_in_user_dir_maps_to_username(self, tmp_path: Path) -> None:
        from ragling.sync import map_file_to_collection

        home = tmp_path / "groups"
        config = Config(home=home, users={"kitchen": UserConfig(api_key="k")})
        name = map_file_to_collection(home / "kitchen" / "notes.md", config)
        assert name == "kitchen"

    def test_file_in_global_dir_maps_to_global(self, tmp_path: Path) -> None:
        from ragling.sync import map_file_to_collection

        global_dir = tmp_path / "global"
        config = Config(global_paths=(global_dir,))
        name = map_file_to_collection(global_dir / "shared.md", config)
        assert name == "global"

    def test_file_outside_known_dirs_returns_none(self, tmp_path: Path) -> None:
        from ragling.sync import map_file_to_collection

        config = Config(home=tmp_path / "groups", global_paths=())
        name = map_file_to_collection(tmp_path / "random" / "file.md", config)
        assert name is None


class TestMapFileToCollectionObsidianAndCode:
    """Tests for mapping files in obsidian vaults and code groups."""

    def test_file_in_obsidian_vault_maps_to_obsidian(self, tmp_path: Path) -> None:
        from ragling.sync import map_file_to_collection

        vault = tmp_path / "vault"
        vault.mkdir()
        config = Config(obsidian_vaults=(vault,))
        name = map_file_to_collection(vault / "notes" / "daily.md", config)
        assert name == "obsidian"

    def test_file_in_code_group_maps_to_group_name(self, tmp_path: Path) -> None:
        from ragling.sync import map_file_to_collection

        repo = tmp_path / "myrepo"
        repo.mkdir()
        config = Config(code_groups=MappingProxyType({"my-org": (repo,)}))
        name = map_file_to_collection(repo / "src" / "main.py", config)
        assert name == "my-org"

    def test_obsidian_vault_not_matched_for_unrelated_file(self, tmp_path: Path) -> None:
        from ragling.sync import map_file_to_collection

        vault = tmp_path / "vault"
        vault.mkdir()
        config = Config(obsidian_vaults=(vault,))
        name = map_file_to_collection(tmp_path / "other" / "file.md", config)
        assert name is None

    def test_code_group_with_multiple_repos(self, tmp_path: Path) -> None:
        from ragling.sync import map_file_to_collection

        repo1 = tmp_path / "repo1"
        repo2 = tmp_path / "repo2"
        repo1.mkdir()
        repo2.mkdir()
        config = Config(code_groups=MappingProxyType({"my-org": (repo1, repo2)}))
        name = map_file_to_collection(repo2 / "lib.py", config)
        assert name == "my-org"

    def test_home_dir_takes_precedence_over_obsidian(self, tmp_path: Path) -> None:
        """If a vault is also inside a user home dir, home mapping wins."""
        from ragling.sync import map_file_to_collection

        home = tmp_path / "groups"
        vault = home / "kitchen" / "vault"
        vault.mkdir(parents=True)
        config = Config(
            home=home,
            users={"kitchen": UserConfig(api_key="k")},
            obsidian_vaults=(vault,),
        )
        name = map_file_to_collection(vault / "note.md", config)
        assert name == "kitchen"


class TestSubmitFileChangeWithMarkerDetection:
    """Tests for submit_file_change using detect_indexer_type_for_file."""

    def test_file_deep_in_obsidian_vault_uses_obsidian_indexer(self, tmp_path: Path) -> None:
        from ragling.sync import submit_file_change

        home = tmp_path / "groups"
        user_dir = home / "kitchen"
        vault = user_dir / "notes"
        vault.mkdir(parents=True)
        (vault / ".obsidian").mkdir()
        deep_file = vault / "daily" / "2025-01-01.md"
        deep_file.parent.mkdir(parents=True)
        deep_file.write_text("# Daily")

        config = Config(
            home=home,
            users={"kitchen": UserConfig(api_key="k")},
        )
        queue = MagicMock()

        submit_file_change(deep_file, config, queue)

        queue.submit.assert_called_once()
        job = queue.submit.call_args[0][0]
        assert job.indexer_type == "obsidian"

    def test_file_deep_in_git_repo_uses_code_indexer(self, tmp_path: Path) -> None:
        from ragling.sync import submit_file_change

        home = tmp_path / "groups"
        user_dir = home / "kitchen"
        repo = user_dir / "myrepo"
        repo.mkdir(parents=True)
        (repo / ".git").mkdir()
        deep_file = repo / "src" / "lib" / "main.py"
        deep_file.parent.mkdir(parents=True)
        deep_file.write_text("print('hello')")

        config = Config(
            home=home,
            users={"kitchen": UserConfig(api_key="k")},
        )
        queue = MagicMock()

        submit_file_change(deep_file, config, queue)

        queue.submit.assert_called_once()
        job = queue.submit.call_args[0][0]
        assert job.indexer_type == "code"


class TestRunStartupSync:
    """Tests for run_startup_sync submitting IndexJobs to the queue."""

    def test_submits_home_directories(self, tmp_path: Path) -> None:
        """Home user directories are submitted with correct indexer_type."""
        from ragling.sync import run_startup_sync

        home = tmp_path / "groups"
        user_dir = home / "kitchen"
        user_dir.mkdir(parents=True)
        (user_dir / ".git").mkdir()

        config = Config(
            home=home,
            users={"kitchen": UserConfig(api_key="k")},
        )
        queue = MagicMock()
        done = threading.Event()

        with patch("ragling.indexers.auto_indexer.detect_directory_type", return_value="code"):
            run_startup_sync(config, queue, done_event=done)
            done.wait(timeout=5.0)

        queue.submit.assert_called()
        job = queue.submit.call_args_list[0][0][0]
        assert isinstance(job, IndexJob)
        assert job.collection_name == "kitchen"
        assert job.indexer_type == "code"
        assert job.path == user_dir

    def test_submits_global_paths(self, tmp_path: Path) -> None:
        """Global paths are submitted with auto-detected indexer_type."""
        from ragling.sync import run_startup_sync

        global_dir = tmp_path / "global"
        global_dir.mkdir()

        config = Config(global_paths=(global_dir,))
        queue = MagicMock()
        done = threading.Event()

        with patch("ragling.indexers.auto_indexer.detect_directory_type", return_value="project"):
            run_startup_sync(config, queue, done_event=done)
            done.wait(timeout=5.0)

        queue.submit.assert_called()
        job = queue.submit.call_args_list[0][0][0]
        assert job.collection_name == "global"
        assert job.indexer_type == "project"
        assert job.path == global_dir

    def test_submits_obsidian_vaults(self, tmp_path: Path) -> None:
        """Obsidian vaults from config are submitted as obsidian indexer_type."""
        from ragling.sync import run_startup_sync

        vault = tmp_path / "vault"
        vault.mkdir()

        config = Config(obsidian_vaults=(vault,))
        queue = MagicMock()
        done = threading.Event()

        run_startup_sync(config, queue, done_event=done)
        done.wait(timeout=5.0)

        queue.submit.assert_called()
        job = queue.submit.call_args_list[0][0][0]
        assert job.collection_name == "obsidian"
        assert job.indexer_type == "obsidian"
        assert job.path == vault

    def test_submits_system_collections(self, tmp_path: Path) -> None:
        """System collections (email, calibre, rss) are submitted."""
        from ragling.sync import run_startup_sync

        config = Config(
            emclient_db_path=tmp_path / "emclient",
            calibre_libraries=(tmp_path / "calibre",),
            netnewswire_db_path=tmp_path / "nnw",
        )
        queue = MagicMock()
        done = threading.Event()

        run_startup_sync(config, queue, done_event=done)
        done.wait(timeout=5.0)

        submitted_types = {call[0][0].indexer_type for call in queue.submit.call_args_list}
        assert "email" in submitted_types
        assert "calibre" in submitted_types
        assert "rss" in submitted_types

    def test_skips_disabled_collections(self, tmp_path: Path) -> None:
        """Disabled collections are not submitted."""
        from ragling.sync import run_startup_sync

        config = Config(
            emclient_db_path=tmp_path / "emclient",
            calibre_libraries=(tmp_path / "calibre",),
            netnewswire_db_path=tmp_path / "nnw",
            disabled_collections=frozenset({"email", "rss"}),
        )
        queue = MagicMock()
        done = threading.Event()

        run_startup_sync(config, queue, done_event=done)
        done.wait(timeout=5.0)

        submitted_types = {call[0][0].indexer_type for call in queue.submit.call_args_list}
        assert "email" not in submitted_types
        assert "rss" not in submitted_types
        assert "calibre" in submitted_types

    def test_submits_code_groups(self, tmp_path: Path) -> None:
        """Code groups from config are submitted with code indexer_type."""
        from ragling.sync import run_startup_sync

        repo = tmp_path / "repo"
        repo.mkdir()

        config = Config(code_groups=MappingProxyType({"my-org": (repo,)}))
        queue = MagicMock()
        done = threading.Event()

        run_startup_sync(config, queue, done_event=done)
        done.wait(timeout=5.0)

        queue.submit.assert_called()
        job = queue.submit.call_args_list[0][0][0]
        assert job.collection_name == "my-org"
        assert job.indexer_type == "code"
        assert job.path == repo

    def test_no_sources_no_submissions(self) -> None:
        """When everything is disabled, nothing is submitted."""
        from ragling.sync import run_startup_sync

        config = Config(
            disabled_collections=frozenset({"email", "calibre", "rss"}),
        )
        queue = MagicMock()
        done = threading.Event()

        run_startup_sync(config, queue, done_event=done)
        done.wait(timeout=5.0)

        queue.submit.assert_not_called()

    def test_done_event_is_set_after_sync(self) -> None:
        from ragling.sync import run_startup_sync

        config = Config(disabled_collections=frozenset({"email", "calibre", "rss"}))
        queue = MagicMock()
        done = threading.Event()

        thread = run_startup_sync(config, queue, done_event=done)
        assert done.wait(timeout=5.0), "done_event was not set"
        thread.join(timeout=5.0)

    def test_done_event_set_even_on_error(self, tmp_path: Path) -> None:
        from ragling.sync import run_startup_sync

        home = tmp_path / "groups"
        home.mkdir()
        config = Config(
            home=home,
            users={"testuser": UserConfig(api_key="k")},
        )
        queue = MagicMock()
        done = threading.Event()

        with patch(
            "ragling.indexers.auto_indexer.collect_indexable_directories",
            side_effect=RuntimeError("boom"),
        ):
            thread = run_startup_sync(config, queue, done_event=done)
            assert done.wait(timeout=5.0), "done_event was not set after error"
            thread.join(timeout=5.0)

    def test_works_without_done_event(self) -> None:
        """Backward compatibility: done_event=None (default) still works."""
        from ragling.sync import run_startup_sync

        config = Config(disabled_collections=frozenset({"email", "calibre", "rss"}))
        queue = MagicMock()

        thread = run_startup_sync(config, queue)
        thread.join(timeout=5.0)
        assert not thread.is_alive()


class TestSubmitFileChange:
    """Tests for submit_file_change submitting IndexJobs to the queue."""

    def test_existing_file_submits_directory_job(self, tmp_path: Path) -> None:
        from ragling.sync import submit_file_change

        home = tmp_path / "groups"
        user_dir = home / "kitchen"
        user_dir.mkdir(parents=True)
        test_file = user_dir / "notes.md"
        test_file.write_text("# Notes")

        config = Config(
            home=home,
            users={"kitchen": UserConfig(api_key="k")},
        )
        queue = MagicMock()

        with patch("ragling.indexers.auto_indexer.detect_directory_type", return_value="project"):
            submit_file_change(test_file, config, queue)

        queue.submit.assert_called_once()
        job = queue.submit.call_args[0][0]
        assert job.collection_name == "kitchen"
        assert job.indexer_type == "project"
        assert job.path == user_dir

    def test_deleted_file_submits_prune_job(self, tmp_path: Path) -> None:
        from ragling.sync import submit_file_change

        home = tmp_path / "groups"
        user_dir = home / "kitchen"
        user_dir.mkdir(parents=True)
        deleted_file = user_dir / "gone.md"

        config = Config(
            home=home,
            users={"kitchen": UserConfig(api_key="k")},
        )
        queue = MagicMock()

        submit_file_change(deleted_file, config, queue)

        queue.submit.assert_called_once()
        job = queue.submit.call_args[0][0]
        assert job.indexer_type == "prune"
        assert job.path == deleted_file
        assert job.collection_name == "kitchen"

    def test_unmapped_file_does_not_submit(self, tmp_path: Path) -> None:
        from ragling.sync import submit_file_change

        config = Config(home=tmp_path / "groups", users={}, global_paths=())
        queue = MagicMock()

        submit_file_change(tmp_path / "random" / "file.md", config, queue)

        queue.submit.assert_not_called()

    def test_unmapped_file_logs_warning(self, tmp_path: Path, caplog) -> None:  # type: ignore[no-untyped-def]
        """submit_file_change logs warning for files not in any configured path."""
        import logging

        from ragling.sync import submit_file_change

        config = Config(home=tmp_path / "groups", users={}, global_paths=())
        queue = MagicMock()

        with caplog.at_level(logging.WARNING, logger="ragling.sync"):
            submit_file_change(tmp_path / "random" / "file.md", config, queue)

        assert any("Cannot map file" in record.message for record in caplog.records)
        queue.submit.assert_not_called()

    def test_global_file_submits_job(self, tmp_path: Path) -> None:
        from ragling.sync import submit_file_change

        global_dir = tmp_path / "global"
        global_dir.mkdir()
        test_file = global_dir / "shared.md"
        test_file.write_text("# Shared")

        config = Config(global_paths=(global_dir,))
        queue = MagicMock()

        with patch("ragling.indexers.auto_indexer.detect_directory_type", return_value="project"):
            submit_file_change(test_file, config, queue)

        queue.submit.assert_called_once()
        job = queue.submit.call_args[0][0]
        assert job.collection_name == "global"


# ---------------------------------------------------------------------------
# Gap S2.9: Re-index handles new entries in system databases
# ---------------------------------------------------------------------------


class TestSystemCollectionReindex:
    """Tests for system collection incremental re-indexing."""

    def test_reindex_job_submitted_for_changed_system_db(self, tmp_path: Path) -> None:
        """When a system DB changes, a re-index job is submitted that will pick up new entries.

        The system watcher submits a full re-index job for the affected collection.
        Incrementality (detecting new vs. existing entries) is handled inside the
        indexer itself, not at the watcher level. This test verifies the watcher
        produces an IndexJob with the correct collection_name and indexer_type.

        NOTE: This overlaps with TestSystemCollectionWatcher.test_submits_job_on_change
        in test_system_watcher.py, which already covers the same behavior. This test
        restates the guarantee from the sync/re-index perspective.
        """
        import time

        from ragling.system_watcher import SystemCollectionWatcher

        email_db = tmp_path / "emclient"
        email_db.mkdir()

        config = Config(
            emclient_db_path=email_db,
            disabled_collections=frozenset({"calibre", "rss"}),
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue, debounce_seconds=0.1)

        watcher.notify_change(email_db)
        time.sleep(0.3)

        queue.submit.assert_called_once()
        job = queue.submit.call_args[0][0]
        assert isinstance(job, IndexJob)
        assert job.collection_name == "email"
        assert job.indexer_type == "email"
        assert job.job_type == "system_collection"


# ---------------------------------------------------------------------------
# Gap S2.10: Re-index handles deleted entries
# ---------------------------------------------------------------------------
# Pruning of deleted entries is handled inside the base indexer's
# prune_stale_sources() function, NOT at the sync/watcher layer.
# This behavior is already thoroughly covered by:
#   tests/test_base_indexer.py::TestPruneStaleSources
#     - test_prunes_source_whose_file_is_gone
#     - test_keeps_source_whose_file_exists
#     - test_skips_sources_without_file_hash
#     - test_skips_sources_with_virtual_uri
#     - test_mixed_sources_only_prunes_missing_files
#   tests/test_base_indexer.py::TestPruneEndToEnd
#     - test_full_lifecycle
# No duplicate test needed here.


# ---------------------------------------------------------------------------
# Gap S4.8: submit_file_change ignores disabled collection
# ---------------------------------------------------------------------------


class TestSubmitFileChangeDisabledCollection:
    """Tests for submit_file_change skipping disabled collections."""

    def test_disabled_collection_does_not_submit(self, tmp_path: Path) -> None:
        """Files in disabled collections are silently skipped."""
        from ragling.sync import submit_file_change

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        note = vault / "daily.md"
        note.write_text("# Note")

        config = Config(
            obsidian_vaults=(vault,),
            disabled_collections=frozenset({"obsidian"}),
        )
        queue = MagicMock()

        submit_file_change(note, config, queue)

        queue.submit.assert_not_called()

    def test_enabled_collection_does_submit(self, tmp_path: Path) -> None:
        """Sanity check: same file with collection enabled DOES submit."""
        from ragling.sync import submit_file_change

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        note = vault / "daily.md"
        note.write_text("# Note")

        config = Config(
            obsidian_vaults=(vault,),
            disabled_collections=frozenset(),
        )
        queue = MagicMock()

        submit_file_change(note, config, queue)

        queue.submit.assert_called_once()
        job = queue.submit.call_args[0][0]
        assert job.collection_name == "obsidian"

    def test_disabled_code_group_does_not_submit(self, tmp_path: Path) -> None:
        """Files in a disabled code group are silently skipped."""
        from ragling.sync import submit_file_change

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        src_file = repo / "main.py"
        src_file.write_text("print('hi')")

        config = Config(
            code_groups=MappingProxyType({"my-org": (repo,)}),
            disabled_collections=frozenset({"my-org"}),
        )
        queue = MagicMock()

        submit_file_change(src_file, config, queue)

        queue.submit.assert_not_called()


# ---------------------------------------------------------------------------
# P2 #2 (S2.3): Startup sync thread name and daemon flag
# ---------------------------------------------------------------------------


class TestStartupSyncThreadProperties:
    """Verify the thread returned by run_startup_sync has correct name and daemon flag."""

    def test_sync_thread_is_daemon_and_named(self) -> None:
        """The startup sync thread should be named 'startup-sync' and be a daemon."""
        from ragling.sync import run_startup_sync

        config = Config(disabled_collections=frozenset({"email", "calibre", "rss"}))
        queue = MagicMock()
        done = threading.Event()

        thread = run_startup_sync(config, queue, done_event=done)

        assert thread.name == "startup-sync"
        assert thread.daemon is True

        # Clean up: wait for the thread to finish
        done.wait(timeout=5.0)
        thread.join(timeout=5.0)
