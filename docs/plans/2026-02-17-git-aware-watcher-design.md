# Git-Aware File Watcher

## Problem

Git commits move HEAD without changing working tree file mtimes. The file watcher filters by supported extensions and never sees `.git/HEAD` or `.git/refs/` changes, so code indexes go stale until manually re-indexed via `rag_index`.

## Solution

Extend the existing watcher and routing to recognize `.git/HEAD` and `.git/refs/` changes as signals to re-index the containing git repo. No new modules or startup wiring needed.

## Changes

### `watcher.py` — `_Handler._handle`

After the extension check fails, check if the path is inside a `.git/` directory AND matches the trigger paths (`.git/HEAD` or anything under `.git/refs/`). If so, enqueue the path.

### `sync.py` — `submit_file_change`

At the top of the function, detect if `file_path` has `.git` in its parts. If so, extract the repo root (parent of the `.git` dir), resolve that to a collection via `_resolve_path`, and submit an `IndexJob(job_type="directory", indexer_type="code")` for the repo root. Return early.

### No changes needed to

- `cli.py` — already watches code group dirs with `recursive=True`
- `get_watch_paths` — already includes code group repos
- `DebouncedIndexQueue` — already debounces rapid events
- `GitRepoIndexer` — already handles incremental indexing via SHA watermarks

## Behavior

1. User commits — git writes `.git/HEAD` and `.git/refs/heads/main`
2. Watchdog fires `on_modified` — handler sees `.git/refs/heads/main`, passes it through
3. `DebouncedIndexQueue` batches the events (2s debounce)
4. `submit_file_change` detects `.git` in path, resolves repo root, submits code re-index job
5. `GitRepoIndexer.index()` compares HEAD SHA vs watermark, does incremental diff, re-indexes changed files

## Alternatives Considered

- **Separate `git_watcher.py`**: More separation of concerns but adds a new module, class, and startup threading for a small feature.
- **Periodic SHA polling**: Simpler but wastes cycles when nothing changes.
- **Post-commit hook**: Most precise but modifies the user's repo.
- **Watch all `.git/` changes**: Noisier — git writes to `.git/objects/`, `.git/index`, `.git/logs/` frequently during normal operations.
