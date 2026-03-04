# Watchers

## Purpose

Filesystem, system database, and config file change monitoring. Detects
changes in configured directories, external SQLite databases, and the
ragling config file, routing events to the indexing pipeline.

## Core Mechanism

`watcher.py` uses watchdog to monitor configured directories with a 2-second
debounced queue (`DebouncedIndexQueue`). `_Handler` filters by file extension
and hidden directories, and passes through git state files (`.git/HEAD`,
`.git/refs/`). `get_watch_paths()` deduplicates paths across config sources.

`system_watcher.py` monitors external SQLite databases (email, calibre, RSS)
via `SystemCollectionWatcher` with a 10-second debounce per collection.

`config_watcher.py` watches the config file via `ConfigWatcher` with a
2-second debounce, preserving the old config on parse errors.

**Key files:**
- `watcher.py` -- filesystem change monitoring with debounced queue
- `system_watcher.py` -- external database monitoring
- `config_watcher.py` -- config file reload

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| `start_watcher(config, callback)` | CLI (serve) | Returns watchdog Observer monitoring configured paths |
| `get_watch_paths(config)` | CLI (serve), `start_watcher()` | Returns deduplicated list of paths to watch |
| `DebouncedIndexQueue` | `start_watcher()` internal | 2-second debounced callback queue (not exported from package) |
| `start_system_watcher(config, callback)` | CLI (serve) | Returns `SystemCollectionWatcher` for external DB monitoring |
| `SystemCollectionWatcher` | CLI (serve) | Monitors email/calibre/RSS databases with 10-second debounce |
| `ConfigWatcher` | CLI (serve) | Debounced config reload with `get_config()` |

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-10 | `_Handler` filters events by file extension (case-insensitive) and skips hidden directories (except `.git/HEAD` and `.git/refs/`) | Prevents indexing binary files, editor temps, and noisy dotfile churn |
| INV-11 | `get_watch_paths()` deduplicates paths that appear in multiple config sources | Prevents duplicate watchdog observers on the same directory |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-6 | Config reload ignored after file change | ConfigWatcher debounce timer not expired; or parse error in new config | Check logs for parse errors; old config preserved on error |

## Testing

```bash
uv run pytest tests/test_watcher.py tests/test_system_watcher.py \
  tests/test_config_watcher.py -v
```

### Coverage

| Spec Item | Test | Description |
|---|---|---|
| INV-10 | `test_watcher.py::TestHandlerExtensionFiltering::test_unsupported_extension_ignored_on_modified` | Unsupported extension does not enqueue |
| INV-10 | `test_watcher.py::TestHandlerExtensionFiltering::test_filtering_is_case_insensitive` | Uppercase extension still matches |
| INV-10 | `test_watcher.py::TestHandlerHiddenDirectoryFiltering::test_file_in_hidden_directory_not_enqueued` | Files in dotdirs skipped |
| INV-10 | `test_watcher.py::TestHandlerGitStateFiles::test_git_head_change_is_enqueued` | `.git/HEAD` changes pass through |
| INV-10 | `test_watcher.py::TestHandlerGitStateFiles::test_git_objects_change_is_not_enqueued` | `.git/objects/` changes filtered out |
| INV-11 | `test_watcher.py::TestWatchPathsIncludesObsidianAndCode::test_deduplicates_overlapping_paths` | Same path in home and obsidian appears once |
| FAIL-6 | `test_config_watcher.py::TestConfigWatcher::test_debounces_rapid_changes` | Rapid changes batched within debounce window |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| `indexer_types.py` (IndexerType) | internal | `src/ragling/SPEC.md` |
| `indexing_queue.py` (IndexingQueue, IndexJob) | internal | `src/ragling/SPEC.md` |
| watchdog | external | N/A -- filesystem event monitoring |
