# Watchers

## Purpose

Filesystem, system database, and config file change monitoring. Detects
changes in configured directories, external SQLite databases, and the
ragling config file, routing events to the indexing pipeline.

## Core Mechanism

Filesystem monitoring uses watchdog with a 2-second debounced queue to batch
rapid changes. External SQLite databases (email, calibre, RSS) are polled with
10-second debounce. Config file changes are debounced at 2 seconds with safe
fallback to old config on parse errors.

Debounce timings are tuned per source type: filesystem events use a 2-second
window (fast enough for interactive feedback), system database changes use
10 seconds (accounts for WAL checkpoint churn from eM Client, Calibre, and
NetNewsWire), and config file changes use 2 seconds with safe fallback to the
previous config on parse errors.

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
| INV-12 | ConfigWatcher preserves the previous valid config if the new config fails to parse | Server must never run with broken configuration; parse errors are logged but do not affect runtime |
| INV-13 | Filesystem watcher exempts `.git/HEAD` and `.git/refs/` from hidden-directory filtering | Enables git-aware re-indexing when the user switches branches or makes commits |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-6 | Config reload ignored after file change | ConfigWatcher debounce timer not expired; or parse error in new config | Check logs for parse errors; old config preserved on error |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| `indexer_types.py` (IndexerType) | internal | `src/ragling/SPEC.md` |
| `indexing_queue.py` (IndexingQueue, IndexJob) | internal | `src/ragling/SPEC.md` |
| watchdog | external | N/A -- filesystem event monitoring |
