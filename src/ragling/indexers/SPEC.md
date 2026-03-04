# Indexers

## Purpose

Source-specific indexing pipelines that discover content, detect changes,
parse via the parsers subsystem, chunk and embed text, and persist results
to the per-group SQLite database. Every indexer extends `BaseIndexer` ABC
and implements the `index()` method.

The key design decision: two-pass indexing (scan for changes, then index
changed sources) combined with three change-detection strategies — file
hash, watermark timestamp, and HEAD SHA comparison — to keep incremental
re-indexing fast across heterogeneous source types.

## Core Mechanism

All indexers follow the same lifecycle: discover sources, check for changes,
parse content, chunk, embed, and persist via `upsert_source_with_chunks()`.
Change detection varies by source type:

- **File hash** (Obsidian, Calibre, git current-state files): SHA-256 of
  file contents compared against stored `file_hash` in the sources table.
- **Watermark timestamp** (email, RSS): latest indexed date stored in the
  collection description; only newer items are fetched from the external DB.
- **HEAD SHA comparison** (git repos): commit SHA stored as a watermark in
  the collection description; `git diff --name-only` identifies changed files.

`ProjectIndexer` auto-discovers nested Obsidian vaults and git repos via
`discover_sources()`, delegates to specialized indexers, and indexes
leftover files directly. Repos already covered by explicit `code_groups`
are excluded to prevent duplicate indexing.

**Key files:**
- `base.py` — `BaseIndexer` ABC, `upsert_source_with_chunks()`,
  `delete_source()`, `prune_stale_sources()`, `IndexResult`, `file_hash()`
- `auto_indexer.py` — `detect_directory_type()`,
  `detect_indexer_type_for_file()`, `collect_indexable_directories()`
- `discovery.py` — `discover_sources()`, `reconcile_sub_collections()`,
  `DiscoveredSource`, `DiscoveryResult`
- `obsidian.py` — `ObsidianIndexer` for Obsidian vault files
- `email_indexer.py` — `EmailIndexer` for eM Client emails
- `calibre_indexer.py` — `CalibreIndexer` for Calibre ebooks
- `git_indexer.py` — `GitRepoIndexer` for code repos (tree-sitter +
  commit history)
- `rss_indexer.py` — `RSSIndexer` for NetNewsWire RSS articles
- `project.py` — `ProjectIndexer` with auto-discovery and delegation,
  `_parse_and_chunk()` shared dispatch, `_EXTENSION_MAP`

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| `BaseIndexer` ABC | All indexers | Must implement `index(conn, config, force, status) -> IndexResult` |
| `upsert_source_with_chunks()` | All indexers | Atomic delete-then-insert of source + documents + vectors; commits transaction |
| `delete_source()` | `GitRepoIndexer`, `prune_stale_sources()` | Removes source row and cascaded documents/vectors; no-op if source absent |
| `prune_stale_sources()` | `ObsidianIndexer`, `CalibreIndexer`, `ProjectIndexer` | Removes file-backed sources whose files no longer exist; skips virtual URIs |
| `file_hash()` | All file-based indexers | Returns SHA-256 hex digest of file contents |
| `IndexResult` | All indexers, `indexing_queue.py` | Dataclass tracking indexed/skipped/skipped_empty/pruned/errors/total_found counts |
| `detect_directory_type()` | `ProjectIndexer`, sync module | Returns `IndexerType.OBSIDIAN`, `CODE`, or `PROJECT` based on marker files |
| `detect_indexer_type_for_file()` | Sync module | Walks parent directories for `.obsidian`/`.git` markers; returns `IndexerType` |
| `collect_indexable_directories()` | Sync module | Filters configured usernames against existing subdirectories |
| `discover_sources()` | `ProjectIndexer` | Recursively scans for `.obsidian`/`.git` markers; returns `DiscoveryResult` |
| `reconcile_sub_collections()` | `ProjectIndexer` | Deletes sub-collections whose markers no longer exist |
| `ObsidianIndexer` | `indexing_queue.py`, `ProjectIndexer` | Indexes all supported file types in Obsidian vaults |
| `EmailIndexer` | `indexing_queue.py` | Indexes emails from eM Client with watermark-based incrementality |
| `CalibreIndexer` | `indexing_queue.py` | Indexes ebooks from Calibre libraries with rich metadata enrichment |
| `GitRepoIndexer` | `indexing_queue.py`, `ProjectIndexer` | Indexes code files (tree-sitter) and optionally commit history |
| `RSSIndexer` | `indexing_queue.py` | Indexes RSS articles from NetNewsWire with watermark-based incrementality |
| `ProjectIndexer` | `indexing_queue.py` | Auto-discovers vaults/repos, delegates to specialized indexers, indexes leftovers |
| `_SUPPORTED_EXTENSIONS` | Core (`watcher.py`) | Frozenset of all indexable file extensions (document + code); defined in `project.py`, imported by Core to filter filesystem events |

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-1 | `upsert_source_with_chunks()` is atomic: delete old documents/vectors, insert new ones, commit in one transaction | Partial writes leave the index in an inconsistent state with orphan vectors or missing documents |
| INV-2 | Every source maps to 1+ documents; every document maps to exactly 1 embedding vector | Search relies on joining sources -> documents -> vec_documents; broken chains produce phantom or missing results |
| INV-3 | File-backed sources use SHA-256 content hash for change detection; virtual sources (email, RSS, commits) use source_path + watermark | Mixing strategies causes either missed updates or unnecessary re-indexing |
| INV-4 | Watermarks stored in `collections.description` field: JSON dict for multi-repo git, ISO timestamp for email/RSS | Watermark loss triggers full re-index; corruption must fall back gracefully |
| INV-5 | `prune_stale_sources()` only removes file-backed sources whose files no longer exist; skips virtual URIs (non-`/` prefix) and sources without file_hash | Pruning virtual sources (email, RSS, calibre descriptions) would permanently delete valid data |
| INV-6 | `ProjectIndexer` excludes repos already covered by explicit `code_groups` to prevent duplicate indexing | Duplicate indexing wastes resources and produces duplicate search results |
| INV-7 | Obsidian indexer skips hidden dirs, `.obsidian`, `.trash`, `.git`, and user-excluded folders | Indexing system/config files pollutes search results with non-content data |
| INV-8 | Database lock retry: 3 attempts with 2s delay for eM Client and NetNewsWire databases | External apps hold locks during normal operation; immediate failure would prevent indexing |
| INV-9 | Per-item errors do not cascade: logged, counted in `IndexResult`, execution continues | One corrupt file or email must not abort the entire indexing run |
| INV-10 | Git indexer routes SPEC.md files to the dedicated spec parser for section-level chunking | SPEC.md files require structural parsing by section, not tree-sitter code parsing |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-1 | Indexing returns errors for email/RSS, no new content indexed | External database locked by eM Client or NetNewsWire | Retry 3x with 2s backoff; `IndexResult` records error after exhaustion; close the external app and retry |
| FAIL-2 | Warning logged, file skipped, error count incremented | File deleted between scan pass and index pass | No action needed; next run will prune the stale source via `prune_stale_sources()` |
| FAIL-3 | Orphaned sub-collections persist after directory restructure | Vault or repo marker removed from a project directory | `reconcile_sub_collections()` deletes sub-collections not in current discovery |
| FAIL-4 | `OllamaConnectionError` propagated, `IndexResult` records error | Ollama embedding API timeout or unavailable | Ensure Ollama is running and the configured model is pulled |
| FAIL-5 | Full re-index triggered unexpectedly | Watermark corruption (invalid JSON, unparseable date) | Parser falls back to empty watermarks, triggering full re-index; manual fix by clearing collection description |

## Testing

```bash
uv run pytest tests/test_base_indexer.py tests/test_auto_indexer.py tests/test_discovery.py tests/test_obsidian_indexer.py tests/test_email_indexer.py tests/test_calibre_indexer.py tests/test_git_indexer.py tests/test_rss_indexer.py tests/test_project_indexer.py -v
```

### Coverage

| Spec Item | Test | Description |
|---|---|---|
| INV-1 | `TestDeleteSource::test_deletes_source_and_documents` | Verifies delete removes source, documents, and vectors atomically |
| INV-1 | `TestPruneEndToEnd::test_full_lifecycle` | End-to-end: index, delete files, prune, verify cascaded cleanup |
| INV-2 | `TestCodeFileIndexing::test_creates_documents_in_db` | Verifies indexing produces document rows in DB |
| INV-2 | `TestCodeFileIndexing::test_creates_vector_embeddings` | Verifies indexing produces vector embedding rows |
| INV-3 | `TestFileHashChangeDetection::test_unchanged_file_hash_causes_skip` | Files with same content hash are skipped on incremental index |
| INV-3 | `TestIncrementalIndexing::test_second_run_no_changes_skips` | Unchanged HEAD SHA causes full skip |
| INV-3 | `TestCalibreIndexerIndex::test_incremental_indexing_skips_unchanged` | Unchanged book hash skips re-indexing |
| INV-4 | `TestWatermarks::test_roundtrip` | JSON watermark serialize/parse roundtrip |
| INV-4 | `TestWatermarks::test_parse_legacy_format` | Legacy `git:path:sha` format still parsed |
| INV-4 | `TestWatermarkPersistence::test_stores_watermark_after_indexing` | Watermark stored in collection description after git index |
| INV-4 | `TestMultiRepoWatermarks::test_two_repos_in_same_collection` | Both repos get watermarks in shared collection |
| INV-5 | `TestPruneStaleSources::test_skips_sources_without_file_hash` | Sources like email with no file_hash are not pruned |
| INV-5 | `TestPruneStaleSources::test_skips_sources_with_virtual_uri` | Virtual URIs (calibre://) are not pruned |
| INV-5 | `TestPruneStaleSources::test_mixed_sources_only_prunes_missing_files` | Only file-backed sources with missing files are pruned |
| INV-6 | `TestProjectIndexerDiscovery::test_repo_in_code_groups_skipped_by_discovery` | Repos in code_groups are not re-indexed by project discovery |
| INV-6 | `TestProjectIndexerDiscovery::test_repo_not_in_code_groups_still_indexed` | Repos NOT in code_groups are still indexed |
| INV-7 | `TestObsidianWalkVaultFiltering::test_skips_hidden_directories` | Files in .obsidian and other hidden dirs excluded |
| INV-7 | `TestObsidianWalkVaultFiltering::test_skips_hidden_files` | Dot-prefixed files excluded |
| INV-7 | `TestObsidianWalkVaultFiltering::test_skips_user_excluded_folders` | User-configured exclude folders honored |
| INV-8 | `TestEmailIndexerChunking::test_index_email_uses_chunk_with_hybrid` | Email indexing uses HybridChunker pipeline (retry logic tested implicitly) |
| INV-9 | `TestObsidianIndexerStatusReporting::test_status_file_processed_called_per_file` | Per-file processing continues after each file (error isolation) |
| INV-10 | `TestSpecMdIndexing::test_spec_md_indexed_as_spec_source_type` | SPEC.md files get source_type='spec' in git repos |
| INV-10 | `TestSpecMdRouting::test_spec_md_uses_spec_parser` | SPEC.md routed to spec parser for section-level chunking |
| FAIL-1 | `TestRSSIndexerChunking::test_index_article_uses_chunk_with_hybrid` | RSS indexing pipeline functional (retry logic in _parse_with_retry) |
| FAIL-2 | `TestPruneStaleSources::test_prunes_source_whose_file_is_gone` | Stale sources are cleaned up on next prune pass |
| FAIL-3 | `TestReconciliation::test_stale_sub_collection_deleted` | Orphaned sub-collections deleted during reconciliation |
| FAIL-3 | `TestReconciliation::test_current_sub_collections_preserved` | Active sub-collections are preserved |
| FAIL-5 | `TestWatermarks::test_parse_invalid_json_returns_empty` | Invalid JSON watermark returns empty dict (triggers full re-index) |
| FAIL-5 | `TestWatermarks::test_parse_unrecognized_string_returns_empty` | Unrecognized watermark format returns empty dict |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| Parsers (markdown, epub, code, email, rss, calibre, spec) | internal | `src/ragling/parsers/SPEC.md` |
| `db.py` (get_or_create_collection, delete_collection) | internal | `src/ragling/SPEC.md` |
| `embeddings.py` (get_embeddings, serialize_float32) | internal | `src/ragling/SPEC.md` |
| `chunker.py` (Chunk) | internal | `src/ragling/SPEC.md` |
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| `doc_store.py` (DocStore) | internal | `src/ragling/SPEC.md` |
| `docling_bridge.py` / `docling_convert.py` | internal | `src/ragling/SPEC.md` |
| `indexing_status.py` (IndexingStatus) | internal | `src/ragling/SPEC.md` |
| `indexer_types.py` (IndexerType) | internal | `src/ragling/SPEC.md` |
| Ollama (embedding API) | external | N/A |
| tree-sitter (code parsing) | external | N/A |
| git CLI | external | N/A |
