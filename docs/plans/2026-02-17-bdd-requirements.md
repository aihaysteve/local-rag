# BDD Requirements Specification

Behavior-Driven Development scenarios for ragling, derived from loosely-phrased requirements using Given/When/Then format. 102 scenarios across 17 features.

| Section | Feature                         | Scenarios |
|---------|---------------------------------|-----------|
| 1       | TLS Security                    | 8         |
| 2       | System Collection Sync          | 10        |
| 3       | Path Sync Coverage              | 8         |
| 4       | Indexer Routing in Sync         | 6         |
| 5       | Extension Maps Purpose          | 7         |
| 6       | Two-Pass Duplicate Prevention   | 4         |
| 7       | Indexing Status File Count      | 6         |
| 8       | File Count Remaining in API     | 3         |
| 9       | Thread Safety of Indexing       | 8         |
| 10      | Stale Entry Detection           | 8         |
| 11      | Search Efficiency               | 6         |
| 12      | N+1 Pattern (Informational)     | 4         |
| 13      | Query Escaping                  | 8         |
| 14      | Config Thread Safety            | 8         |
| 15      | DocStore/Debounce Thread Safety | 7         |
| 16      | Hash Consolidation              | 3         |
| 17      | Docstring Improvement           | 6         |

---

## Section 1: TLS Security

Feature: TLS-secured MCP transport
  The MCP server shall serve over modern TLS when using SSE transport.
  Installation shall automatically generate and trust certificates.

```gherkin
Background:
  Given no TLS certificates exist in ~/.ragling/tls/

Scenario: Auto-generate CA and server certificates on first serve
  When the server starts in SSE mode
  Then a CA certificate is generated at ~/.ragling/tls/ca.pem
  And a CA private key is generated at ~/.ragling/tls/ca-key.pem
  And a server certificate is generated at ~/.ragling/tls/server.pem
  And a server private key is generated at ~/.ragling/tls/server-key.pem
  And the CA key file has permissions 0600
  And the server key file has permissions 0600

Scenario: Server certificate includes required SANs
  When certificates are generated
  Then the server certificate includes SAN DNS:localhost
  And the server certificate includes SAN DNS:host.docker.internal
  And the server certificate includes SAN IP:127.0.0.1

Scenario: Server certificate is signed by the generated CA
  When certificates are generated
  Then the server certificate's issuer matches the CA certificate's subject
  And the server certificate can be verified against the CA certificate

Scenario: Auto-renew expired server certificate
  Given a server certificate that has expired
  And the CA certificate still exists and is valid
  When the server starts in SSE mode
  Then a new server certificate is generated
  And the new certificate is signed by the existing CA

Scenario: Warn on near-expiry server certificate
  Given a server certificate expiring in fewer than 30 days
  When the server starts in SSE mode
  Then a warning is logged indicating the number of days until expiry

Scenario: SSE transport serves over HTTPS
  Given valid TLS certificates exist
  When the server starts with --sse
  Then uvicorn is configured with ssl_certfile and ssl_keyfile
  And the server listens on HTTPS (not HTTP)

Scenario: Token authentication requires TLS
  Given the server is configured with user API keys
  When a client connects over SSE
  Then Bearer tokens are transmitted over an encrypted TLS connection
  And tokens are not visible to other processes on the network

Scenario: CA certificate is available for client trust
  Given TLS certificates have been generated
  When "ragling mcp-config" is run
  Then the output includes the ca_cert path
  And the CA certificate at that path can be used to verify the server
```

---

## Section 2: System Collection Sync at Startup and Runtime

Feature: System collection synchronization
  The system shall synchronize system collections (email, calibre, RSS)
  at startup and continue monitoring for changes at runtime.

```gherkin
# --- Startup Sync ---

Scenario: Sync enabled system collections at startup
  Given the config has email, calibre, and RSS collections enabled
  When the server starts
  Then an IndexJob is submitted for the email collection
  And an IndexJob is submitted for the calibre collection
  And an IndexJob is submitted for the RSS collection

Scenario: Skip disabled system collections at startup
  Given the config has "email" in disabled_collections
  When the server starts
  Then no IndexJob is submitted for the email collection
  And IndexJobs are submitted for other enabled system collections

Scenario: Startup sync runs in a background thread
  When the server starts
  Then startup sync runs in a daemon thread named "startup-sync"
  And the done_event is set when all jobs have been submitted
  And the server remains responsive during sync

# --- Runtime Monitoring ---

Scenario: Detect email database changes at runtime
  Given the server is running and startup sync has completed
  When the eM Client SQLite database file is modified
  Then after the debounce period (default 10 seconds)
  Then an IndexJob of type "system_collection" is submitted for email

Scenario: Detect calibre database changes at runtime
  Given the server is running and startup sync has completed
  When a file in a calibre library directory is modified
  Then after the debounce period
  Then an IndexJob is submitted for calibre

Scenario: Detect RSS database changes at runtime
  Given the server is running and startup sync has completed
  When the NetNewsWire SQLite database file is modified
  Then after the debounce period
  Then an IndexJob is submitted for RSS

Scenario: Debounce rapid successive changes
  Given the server is running
  When the email database is modified 5 times within 3 seconds
  Then only one IndexJob is submitted for email
  And the job is submitted after the debounce period expires
    from the last modification

Scenario: Runtime monitoring starts only after startup sync completes
  When the server starts
  Then the system collection watcher does not start
    until the startup sync done_event is set

# --- Deletions and Insertions ---

Scenario: Re-index handles new entries in system databases
  Given the email collection was previously indexed with 100 emails
  When the email database is modified (new emails added)
  And the re-index job completes
  Then newly added emails are indexed
  And previously indexed emails that haven't changed are skipped

Scenario: Re-index handles deleted entries in system databases
  Given the email collection was previously indexed
  When the email database is modified (emails deleted)
  And the re-index job completes
  Then entries for deleted emails are pruned from the index
```

---

## Section 3: Path Sync Coverage

Feature: Comprehensive path synchronization
  The system shall sync all configured path types at startup:
  home directories, global paths, obsidian vaults, code groups,
  and system sources.

```gherkin
Scenario: Sync home user directories
  Given the config has home="/data/home" with users ["alice", "bob"]
  And the directories /data/home/alice and /data/home/bob exist
  When startup sync runs
  Then an IndexJob is submitted for collection "alice"
  And an IndexJob is submitted for collection "bob"

Scenario: Skip non-existent user directories
  Given the config has users ["alice", "bob"]
  And only /data/home/alice exists
  When startup sync runs
  Then an IndexJob is submitted for "alice"
  And no IndexJob is submitted for "bob"

Scenario: Sync global paths
  Given the config has global_paths ["/shared/docs", "/shared/reports"]
  And the global collection is enabled
  When startup sync runs
  Then IndexJobs are submitted for collection "global"
    with paths /shared/docs and /shared/reports

Scenario: Sync obsidian vaults
  Given the config has obsidian_vaults ["~/Notes", "~/Work"]
  And the obsidian collection is enabled
  When startup sync runs
  Then IndexJobs are submitted for collection "obsidian"
    with indexer_type "obsidian" for each vault path

Scenario: Sync code groups
  Given the config has code_groups {"myorg": ["/repos/a", "/repos/b"]}
  And the "myorg" collection is enabled
  When startup sync runs
  Then IndexJobs are submitted for collection "myorg"
    with indexer_type "code" for each repo path

Scenario: Auto-detect directory type for home directories
  Given a home user directory contains a .obsidian marker
  When startup sync processes that directory
  Then the IndexJob has indexer_type "obsidian"

Scenario: Auto-detect git repo for home directories
  Given a home user directory contains a .git marker
  When startup sync processes that directory
  Then the IndexJob has indexer_type "code"

Scenario: Default to project type for unmarked directories
  Given a home user directory has no .obsidian or .git marker
  When startup sync processes that directory
  Then the IndexJob has indexer_type "project"
```

---

## Section 4: Indexer Routing in Sync

Feature: Sync creates correct indexer based on collection type
  When syncing files, the system shall select the correct category
  indexer based on the directory/collection type of the file.

```gherkin
# --- Directory-level routing (startup sync) ---

Scenario Outline: Route directory jobs to correct indexer
  Given an IndexJob with indexer_type "<indexer_type>"
  When the indexing queue worker processes the job
  Then the <indexer_class> is instantiated and run

  Examples:
    | indexer_type | indexer_class    |
    | obsidian     | ObsidianIndexer  |
    | code         | GitRepoIndexer   |
    | project      | ProjectIndexer   |
    | email        | EmailIndexer     |
    | calibre      | CalibreIndexer   |
    | rss          | RSSIndexer       |

Scenario: Reject unknown indexer type
  Given an IndexJob with indexer_type "unknown"
  When the indexing queue worker processes the job
  Then a ValueError is raised with message containing "Unknown indexer_type"

# --- File-level routing (watcher changes) ---

Scenario: Route changed file to correct indexer by walking parents
  Given a file at /data/home/alice/notes/.obsidian exists (vault marker)
  And a file /data/home/alice/notes/daily/2024-01-01.md is modified
  When submit_file_change is called
  Then the IndexJob has indexer_type "obsidian"
  And the IndexJob has collection_name "alice"

Scenario: Route changed file in git repo to code indexer
  Given a file at /data/home/bob/project/.git exists (repo marker)
  And a file /data/home/bob/project/src/main.py is modified
  When submit_file_change is called
  Then the IndexJob has indexer_type "code"

Scenario: Route changed file with no markers to project indexer
  Given a directory /shared/docs with no .obsidian or .git marker
  And a file /shared/docs/report.pdf is modified
  When submit_file_change is called
  Then the IndexJob has indexer_type "project"

Scenario: Submit prune job for deleted file
  Given a file /data/home/alice/notes/old.md previously existed
  And the file has been deleted from disk
  When submit_file_change is called
  Then the IndexJob has job_type "file_deleted"
  And the IndexJob has indexer_type "prune"

Scenario: Ignore file not belonging to any configured path
  Given a file /tmp/random.txt is changed
  And /tmp is not under any configured home, global, vault, or code path
  When submit_file_change is called
  Then no IndexJob is submitted
  And a warning is logged

Scenario: Ignore file in disabled collection
  Given a file belongs to collection "obsidian"
  And "obsidian" is in disabled_collections
  When submit_file_change is called
  Then no IndexJob is submitted
```

---

## Section 5: Extension Maps — Purpose and Consolidation

Feature: Extension map clarity and purpose
  _EXTENSION_MAP maps file extensions to source_type strings for
  document indexing. _CODE_EXTENSION_MAP maps extensions to language
  names for tree-sitter code parsing. Their purposes are distinct
  and shall not be conflated.

```gherkin
# --- _EXTENSION_MAP (project.py) ---

Scenario: _EXTENSION_MAP determines which files are indexable
  Given a directory containing files with various extensions
  When _collect_files scans the directory
  Then only files whose extension (lowercased) appears in
    _EXTENSION_MAP are included
  And files with unknown extensions are skipped with a debug log

Scenario: _EXTENSION_MAP provides source_type for indexed documents
  Given a file with extension ".pdf"
  When the file is indexed
  Then the source_type stored in the database is "pdf"
    (the value from _EXTENSION_MAP[".pdf"])

Scenario: Obsidian indexer uses _EXTENSION_MAP for attachment filtering
  Given an Obsidian vault containing .md, .pdf, .png, and .xyz files
  When the ObsidianIndexer scans the vault
  Then .md, .pdf, and .png files are indexed
  And .xyz files are skipped because they are not in _EXTENSION_MAP

# --- _CODE_EXTENSION_MAP (code.py) ---

Scenario: _CODE_EXTENSION_MAP determines which files get tree-sitter parsing
  Given a git repo containing .py, .js, .md, and .pdf files
  When the GitRepoIndexer scans the repo
  Then .py and .js files are parsed with tree-sitter
    (extensions present in _CODE_EXTENSION_MAP)
  And .md and .pdf files are not parsed as code

Scenario: _CODE_EXTENSION_MAP provides language names for tree-sitter
  Given a file with extension ".py"
  When is_code_file returns True
  Then get_language_for_file returns "python"
    (the value from _CODE_EXTENSION_MAP[".py"])

# --- Watcher uses _EXTENSION_MAP for filtering ---

Scenario: File watcher only triggers for supported extensions
  Given the watcher is monitoring a directory
  When a file with extension ".pdf" is created
  Then a change event is emitted (extension in _EXTENSION_MAP)

Scenario: File watcher ignores unsupported extensions
  Given the watcher is monitoring a directory
  When a file with extension ".xyz" is created
  Then no change event is emitted
```

---

## Section 6: Two-Pass Scan Duplicate Prevention

Feature: Two-pass scan shall not produce duplicate index entries
  Collections that use two-pass scanning (discovery pass for
  vaults/repos, then a second pass for remaining supported files)
  shall not index the same file twice.

```gherkin
Scenario: Files inside discovered vaults are not re-indexed as leftovers
  Given a project directory containing:
    | path                          | type     |
    | vault/.obsidian/              | marker   |
    | vault/note.md                 | markdown |
    | vault/attachment.pdf          | pdf      |
    | standalone.pdf                | pdf      |
  When the ProjectIndexer runs
  Then vault/note.md is indexed by the ObsidianIndexer (pass 1)
  And vault/attachment.pdf is indexed by the ObsidianIndexer (pass 1)
  And standalone.pdf is indexed as a leftover (pass 2)
  And no file appears in the index more than once

Scenario: Files inside discovered git repos are not re-indexed as leftovers
  Given a project directory containing:
    | path                     | type   |
    | repo/.git/               | marker |
    | repo/src/main.py         | code   |
    | repo/README.md           | md     |
    | notes.txt                | txt    |
  When the ProjectIndexer runs
  Then repo/src/main.py is indexed by the GitRepoIndexer (pass 1)
  And notes.txt is indexed as a leftover (pass 2)
  And no file appears in the index more than once

Scenario: Leftover collection excludes claimed subtrees
  Given a discovery result with claimed paths [/project/vault, /project/repo]
  When _collect_leftovers walks /project
  Then files under /project/vault are excluded
  And files under /project/repo are excluded
  And only files outside claimed subtrees are returned

Scenario: Upsert prevents duplicates even if submitted twice
  Given a file "report.pdf" with source_path "/project/report.pdf"
  When upsert_source_with_chunks is called twice for the same source_path
  Then only one source row exists in the database
  And the second call replaces the first call's documents and vectors
```

---

## Section 7: Indexing Status Tracks File Count (Not Directory Count)

Feature: Indexing status tracks file counts, not directory counts
  Progress reporting shall show the number of files being indexed,
  not the number of directories submitted as jobs.

```gherkin
Scenario: File-level tracking reports individual files
  Given the indexing status is initialized
  When set_file_total("obsidian", 150) is called
  And file_processed("obsidian", 1) is called 55 times
  Then to_dict() reports obsidian as:
    {"total": 150, "processed": 55, "remaining": 95}

Scenario: File-level tracking takes precedence over job-level
  Given both job-level and file-level counts exist for "obsidian"
  When to_dict() is called
  Then the obsidian entry shows the file-level dict
    (not the job-level integer)

Scenario: Job-level tracking shows integer count
  Given only job-level counts exist for "email" (no file-level)
  When to_dict() is called
  Then the email entry shows an integer (e.g., 2)

Scenario: Total remaining aggregates across all collections
  Given file-level: obsidian has 50 remaining
  And job-level: email has 1 remaining
  When to_dict() is called
  Then total_remaining is 51

Scenario: Idle status returns None
  Given no indexing is in progress
  When to_dict() is called
  Then it returns None

Scenario: Collections are removed when complete
  Given job-level count for "email" is 1
  When decrement("email") is called
  Then "email" no longer appears in _counts
  And if no other collections are active, to_dict() returns None
```

---

## Section 8: Report File Count Remaining Per Collection

Feature: Report indexing file count remaining per collection
  Search responses shall include per-collection file counts
  remaining when indexing is active.

```gherkin
Scenario: Search response includes indexing status when active
  Given indexing is in progress with:
    | collection | total | processed |
    | obsidian   | 200   | 120       |
    | calibre    | 50    | 10        |
  When rag_search is called
  Then the response includes an "indexing" key
  And indexing.active is True
  And indexing.total_remaining is 120
    (200-120 + 50-10 = 80+40 = 120)
  And indexing.collections.obsidian.remaining is 80
  And indexing.collections.calibre.remaining is 40

Scenario: Search response omits indexing status when idle
  Given no indexing is in progress
  When rag_search is called
  Then the response "indexing" key is None

Scenario: List collections response includes indexing status
  Given indexing is in progress
  When rag_list_collections is called
  Then the response includes the same indexing status structure
```

---

## Section 9: Thread Safety of Indexing Operations

Feature: Thread-safe indexing operations
  The system shall be thread-safe for all indexing operations.
  A single worker thread shall process indexing jobs sequentially,
  ensuring only one thread writes to the database at a time.

```gherkin
# --- Single-writer design ---

Scenario: Only the worker thread writes to the index database
  Given the indexing queue is started
  When multiple IndexJobs are submitted from different threads
  Then all jobs are processed sequentially by the single worker thread
  And no two indexing operations write to the database concurrently

Scenario: Concurrent job submission is safe
  Given the indexing queue is running
  When 10 threads each call submit() simultaneously
  Then all 10 jobs are enqueued without error
  And all 10 jobs are eventually processed by the worker

Scenario: Submit-and-wait blocks caller until completion
  Given the indexing queue is running
  When a thread calls submit_and_wait(job, timeout=300)
  Then the calling thread blocks until the worker completes the job
  And the IndexResult is returned to the caller

Scenario: Submit-and-wait returns None on timeout
  Given the indexing queue is running
  And the worker is busy with a long-running job
  When a thread calls submit_and_wait(job, timeout=0.01)
  And the job does not complete within 0.01 seconds
  Then submit_and_wait returns None
  And the job remains in the queue for eventual processing

# --- Queue shutdown ---

Scenario: Graceful shutdown completes in-flight work
  Given the worker is processing a job
  When shutdown() is called
  Then the worker finishes the current job
  And the worker thread exits within 30 seconds

Scenario: Shutdown sentinel stops the worker loop
  When shutdown() is called
  Then a None sentinel is placed on the queue
  And the worker exits its processing loop when it dequeues None

# --- DocStore access is single-threaded ---

Scenario: DocStore is only accessed from the worker thread
  Given indexers that use DocStore (obsidian, calibre, project)
  When these indexers run via the queue worker
  Then DocStore.get_or_convert is called only from the worker thread
  And no additional locking is needed on DocStore

# --- Error isolation ---

Scenario: Worker continues after an indexer raises an exception
  Given the indexing queue has jobs [A, B, C]
  And job B's indexer raises an exception
  When the worker processes the queue
  Then job A completes successfully
  And job B's exception is logged
  And job C is still processed after B's failure
  And the status counter for B is decremented

Scenario: IndexRequest done event is set even on failure
  Given a submit_and_wait call for a job that will fail
  When the worker encounters the exception
  Then the done event is set (caller unblocks)
  And the result is None
```

---

## Section 10: Stale Entry Detection During Search

Feature: Stale entry detection during search
  The system shall check for stale entries during search without
  incurring excessive overhead. Results from files that have been
  modified or deleted since indexing shall be flagged.

```gherkin
# --- Staleness detection ---

Scenario: Mark result as stale when source file has been deleted
  Given a search result with source_path "/docs/report.pdf"
  And the file /docs/report.pdf no longer exists on disk
  When _mark_stale_results processes the result
  Then result.stale is True

Scenario: Mark result as stale when source file has been modified
  Given a search result indexed at file_modified_at "2024-01-01T00:00:00"
  And the file's current mtime is "2024-06-15T12:00:00"
  When _mark_stale_results processes the result
  Then result.stale is True

Scenario: Do not mark result as stale when file is unchanged
  Given a search result indexed at file_modified_at "2024-06-15T12:00:00"
  And the file's current mtime matches the indexed timestamp
  When _mark_stale_results processes the result
  Then result.stale is False

Scenario: Skip staleness check for non-filesystem sources
  Given search results with source_paths:
    | source_path                  | type          |
    | msg://email-id-123           | email         |
    | https://feed.example.com/1   | rss           |
    | calibre://book/42            | calibre desc  |
  When _mark_stale_results processes the results
  Then none of these results have stale set to True
  And no stat() calls are made for these paths

# --- Performance ---

Scenario: Stat cache prevents redundant filesystem calls
  Given 5 search results from the same source file "/docs/big.pdf"
  When _mark_stale_results processes the results
  Then os.stat is called exactly once for "/docs/big.pdf"
  And all 5 results share the same stale determination

Scenario: Stale flag is included in search API response
  Given a search returns results where one is stale
  When rag_search formats the response
  Then each result dict includes a "stale" boolean field
  And the stale result has stale=True

# --- Graceful degradation ---

Scenario: Handle permission errors during stat
  Given a search result for a file that exists but is not readable
  When os.stat raises a PermissionError
  Then result.stale is True (conservative: treat as stale)

Scenario: Handle missing file_modified_at metadata
  Given a search result with file_modified_at=None in the database
  And the source file exists on disk
  When _mark_stale_results processes the result
  Then result.stale remains False (cannot determine staleness)
```

---

## Section 11: Search Efficiency Optimization

Feature: Search efficiency optimization
  Search shall be optimized to scale with collection size.
  Avoid N+1 query patterns. Use batch loading and caching.

```gherkin
# --- Batch metadata loading ---

Scenario: Metadata is loaded in a single batch query
  Given vector search returns 30 candidate document IDs
  When _batch_load_metadata is called with those IDs
  Then a single SQL query with IN(...) clause fetches all metadata
  And no per-document queries are executed

Scenario: Metadata cache is shared between vector and FTS pipelines
  Given a metadata_cache dict is passed to both searches
  When _vector_search loads metadata for doc IDs [1, 2, 3]
  And _fts_search later needs metadata for doc IDs [2, 3, 4]
  Then only doc ID 4 is fetched from the database
  And doc IDs 2 and 3 are served from the cache

Scenario: Cache prevents redundant loads during RRF merge
  Given vector and FTS results overlap on 5 document IDs
  When rrf_merge produces the final top_k results
  And _batch_load_metadata is called for the merged IDs
  Then overlapping IDs are already cached and not re-queried

# --- Oversampling ---

Scenario: Unfiltered search uses minimal oversampling
  Given no filters are active
  And top_k is 10
  When vector/FTS search determines the candidate limit
  Then the limit is top_k * 3 = 30

Scenario: Filtered search uses higher oversampling
  Given filters are active (e.g., collection="obsidian")
  And top_k is 10
  When vector/FTS search determines the candidate limit
  Then the limit is top_k * 50 = 500
  And post-filter selects the top 10 matching results

# --- Early termination ---

Scenario: Filter application stops at top_k matches
  Given 500 oversampled candidates
  And top_k is 10
  When _apply_filters iterates through candidates
  Then iteration stops as soon as 10 matching candidates are found
  And remaining candidates are not checked

# --- Empty result short-circuits ---

Scenario: Empty visible_collections returns immediately
  Given visible_collections is an empty list
  When search() is called
  Then an empty list is returned without any database queries

Scenario: Empty FTS query returns immediately
  Given a query that produces an empty string after escaping
  When _fts_search is called
  Then an empty list is returned without executing a query
```

---

## Section 12: N+1 Query Pattern (Informational)

Feature: N+1 query pattern avoidance (informational)
  The N+1 query pattern occurs when code loads a list of N items,
  then issues a separate query for each item's related data,
  resulting in 1 + N total queries instead of 2.

```gherkin
# --- The anti-pattern ---

Scenario: N+1 anti-pattern example (DO NOT DO THIS)
  Given 100 search result document IDs
  When metadata is loaded one-at-a-time in a loop:
    for doc_id in results:
        metadata = query("SELECT ... WHERE id = ?", doc_id)
  Then 100 separate SQL queries are executed
  And performance degrades linearly with result count

# --- The correct pattern (already implemented) ---

Scenario: Batch loading avoids N+1
  Given 100 search result document IDs
  When _batch_load_metadata is called with all 100 IDs
  Then 1 SQL query with IN(?, ?, ..., ?) is executed
  And all 100 rows are returned in a single round-trip

# --- Other N+1 instances to watch for ---

Scenario: Pruning checks files in batch
  Given prune_stale_sources loads all source_paths for a collection
  When it checks each path with Path.exists()
  Then the source_paths are loaded in a single query
  And only the filesystem stat calls are per-file (unavoidable)

Scenario: Delete cascades use batch operations
  Given a source with 50 document chunks to delete
  When delete_source is called
  Then document IDs are collected in one query
  And vec_documents deletion uses a single IN(...) clause
  And documents deletion uses a single WHERE source_id = ?
```

---

## Section 13: Query Escaping

Feature: Query escaping for FTS5
  All user-supplied search queries shall be properly escaped
  before use in FTS5 MATCH clauses. A centralized escape function
  shall be used at all FTS entry points.

```gherkin
# --- Escaping behavior ---

Scenario: Normal query is wrapped in double quotes
  Given the query "kubernetes deployment"
  When escape_fts_query processes it
  Then the result is '"kubernetes deployment"'

Scenario: Embedded double quotes are doubled
  Given the query 'search for "exact phrase"'
  When escape_fts_query processes it
  Then the result is '"search for ""exact phrase"""'

Scenario: FTS operators are neutralized by quoting
  Given the query "foo AND bar OR baz NOT qux"
  When escape_fts_query processes it
  Then the result is '"foo AND bar OR baz NOT qux"'
  And FTS treats AND/OR/NOT as literal words, not operators

Scenario: Whitespace-only query returns empty string
  Given the query "   "
  When escape_fts_query processes it
  Then the result is ""
  And _fts_search returns an empty list without querying

Scenario: Empty query returns empty string
  Given the query ""
  When escape_fts_query processes it
  Then the result is ""

Scenario: Special FTS5 characters are safely handled
  Given the query "column:value AND prefix*"
  When escape_fts_query processes it
  Then the result wraps the entire input as a phrase literal
  And FTS does not interpret "column:" as a column filter
  And FTS does not interpret "*" as a prefix operator

# --- Centralized usage ---

Scenario: All FTS search paths use escape_fts_query
  Given a search query enters the system via rag_search or CLI
  When the query reaches _fts_search
  Then escape_fts_query is called before the MATCH clause
  And no raw user input is ever passed directly to FTS5 MATCH

Scenario: FTS query failure is handled gracefully
  Given an escaped query that still causes an FTS OperationalError
  When _fts_search catches the exception
  Then a warning is logged with the safe query and error
  And an empty result list is returned (search degrades to vector-only)

# --- SQL parameterization layer ---

Scenario: All SQL queries use parameterized placeholders
  Given any query in search.py, base.py, or db.py
  When user-supplied values are passed to SQLite
  Then they are always passed as ? parameters
  And no f-string interpolation of user values occurs
  And IN(...) clauses use dynamically generated ? placeholders
    (not user-controlled values in the SQL string)

# --- Static analysis ---

Scenario: Ruff S608 flags suspicious SQL string formatting
  Given the ruff config extends select with S608
  When ruff check runs on the codebase
  Then any f-string used in SQL without a noqa comment is flagged
  And existing noqa:S608 comments document why each usage is safe
    (parameterized placeholders, not user input)
```

---

## Section 14: Thread Safety of Configuration

Feature: Thread-safe configuration management
  Configuration mutations shall be thread-safe. The system shall
  synchronize with configuration changes at runtime.

```gherkin
# --- Immutable Config ---

Scenario: Config dataclass is frozen (immutable)
  Given a Config instance
  When any code attempts to set an attribute directly
  Then a FrozenInstanceError is raised
  And the original Config is unchanged

Scenario: Config changes produce new instances via with_overrides
  Given a Config with group_name="default"
  When config.with_overrides(group_name="work") is called
  Then a new Config instance is returned with group_name="work"
  And the original Config still has group_name="default"

# --- ConfigWatcher thread safety ---

Scenario: Config reads are thread-safe
  Given the ConfigWatcher holds a Config reference
  When multiple threads call get_config() concurrently
  Then all threads receive a valid Config instance
  And no partial/torn reads occur

Scenario: Config replacement is atomic
  Given the config file is modified on disk
  When the ConfigWatcher debounce timer fires
  Then load_config parses the new file
  And the internal _config reference is replaced under a lock
  And subsequent get_config() calls return the new Config

Scenario: Invalid config file preserves current config
  Given the config file is modified to contain invalid JSON
  When the ConfigWatcher attempts to reload
  Then an exception is logged
  And get_config() continues to return the previous valid Config

# --- Propagation to dependent systems ---

Scenario: Config reload updates the indexing queue
  Given the ConfigWatcher has an on_reload callback
  When the config is successfully reloaded
  Then the callback is invoked with the new Config
  And indexing_queue.set_config(new_config) is called

Scenario: Queue worker reads fresh config per job
  Given the indexing queue's _config was replaced via set_config
  When the worker starts processing the next job
  Then it uses the new Config (not the stale one)

# --- Runtime config change actions ---

Scenario: Adding a new collection to config triggers sync
  Given the config previously had no obsidian_vaults
  When the user edits config to add obsidian_vaults=["/Notes"]
  And the config is reloaded
  Then the on_reload callback can detect the new vault
  And new indexing jobs can be submitted for the new source

Scenario: Disabling a collection stops future indexing
  Given "rss" is not in disabled_collections
  When the user edits config to add "rss" to disabled_collections
  And the config is reloaded
  Then subsequent startup syncs skip the RSS collection
  And the system watcher stops submitting RSS jobs

Scenario: Debounce prevents rapid reloads
  Given the config file is saved 5 times in 1 second
  When the ConfigWatcher receives 5 notify_change calls
  Then only one reload occurs (after the 2-second debounce)
```

---

## Section 15: Thread Safety of DocStore and Debounce Queue

Feature: Thread safety of DocStore and debounce queues

```gherkin
# --- DocStore ---

Scenario: DocStore is thread-safe by single-writer design
  Given DocStore is only accessed from the indexing worker thread
  When get_or_convert is called during indexing
  Then no concurrent writes occur on the DocStore connection
  And WAL mode allows concurrent readers from MCP search threads

Scenario: DocStore WAL mode enables concurrent reads
  Given the DocStore database uses WAL journal mode
  When one MCP instance is indexing (writing)
  And another MCP instance calls rag_doc_store_info (reading)
  Then both operations succeed without blocking

Scenario: DocStore busy_timeout prevents immediate lock failures
  Given concurrent access to DocStore
  When a write lock is momentarily held
  Then readers wait up to 5000ms before failing
  And normal operations complete within the timeout

# --- SystemCollectionWatcher debounce ---

Scenario: Debounce timer is reset on each change
  Given a system DB file triggers a change event
  And the debounce timer is already running for that path
  When another change event arrives before the timer fires
  Then the old timer is cancelled
  And a new timer is started from zero

Scenario: Debounce timer state is protected by lock
  Given multiple watchdog threads detect changes simultaneously
  When they call notify_change concurrently
  Then the RLock ensures timer operations are atomic
  And no timer is lost or double-fired

Scenario: Stop flushes all pending changes
  Given debounce timers are running for email and RSS
  When stop() is called
  Then all timers are cancelled
  And pending paths are flushed immediately (jobs submitted)
  And no timer callbacks fire after stop returns

# --- ConfigWatcher debounce ---

Scenario: ConfigWatcher debounce timer is thread-safe
  Given multiple filesystem events for the config file
  When notify_change is called from different watchdog threads
  Then the lock ensures only one timer is active
  And stop() cancels any pending timer cleanly
```

---

## Section 16: Consolidate Duplicated Hash Functions

Feature: Consolidate duplicated hash functions
  The file_hash function shall exist in exactly one location.
  All consumers shall import from that single source.

```gherkin
Scenario: file_hash is defined in one module
  Given the function file_hash(path: Path) -> str
  When searching the codebase for its definition
  Then it is defined in exactly one module
  And all other modules import it from that single source

Scenario: doc_store.py imports file_hash from base.py
  Given doc_store.py needs to hash file contents
  When it computes a content hash
  Then it uses the imported file_hash from indexers.base
  And does not define its own hash function

Scenario: file_hash produces consistent SHA-256 output
  Given a file with known contents
  When file_hash is called
  Then the result matches hashlib.sha256(contents).hexdigest()
  And the result is stable across calls for the same file content
```

Note: As of current code, doc_store.py line 14 already imports
`file_hash` from `indexers.base` as `_file_hash`. This requirement
appears to be satisfied.

---

## Section 17: Improve rag_search Docstring

Feature: rag_search docstring follows Pythonic conventions
  The rag_search docstring shall follow PEP 257 and Google/NumPy
  style conventions while remaining useful as an MCP tool description.

```gherkin
Scenario: Docstring has a concise one-line summary
  Given the rag_search function
  When the docstring is inspected
  Then the first line is a concise imperative summary
    (e.g., "Search indexed collections using hybrid vector + FTS.")
  And it fits on one line (under 79 characters)

Scenario: Summary is separated from body by a blank line
  Given the rag_search docstring
  When parsed by documentation tools
  Then a blank line separates the summary from the extended description

Scenario: Args section documents all parameters
  Given rag_search accepts: query, collection, top_k, source_type,
    date_from, date_to, sender, author
  When the Args section is inspected
  Then each parameter has a type and description
  And the descriptions match the actual parameter behavior

Scenario: Returns section documents the return type
  Given rag_search returns dict[str, Any]
  When the Returns section is inspected
  Then it describes the structure: results list and indexing status

Scenario: Extended description serves dual purpose
  Given the docstring is used both by Python tooling and MCP clients
  When an MCP client reads the tool description
  Then the collection types, filter options, and examples are present
  And a developer reading help(rag_search) gets useful information

Scenario: No redundancy between Args and extended description
  Given the extended description lists filter options
  When compared to the Args section
  Then filter details appear in one place, not both
  And Args provides type+constraint info
  And the extended description provides usage context and examples
```

---

## Test Coverage Audit

Audit of existing tests against the 102 BDD scenarios above. Each scenario
is classified as COVERED, PARTIAL, or GAP based on existing test files.

### Coverage Summary

| Section | Feature                         | Covered | Partial | Gap |
|---------|---------------------------------|---------|---------|-----|
| 1       | TLS Security                    | 5       | 1       | 2   |
| 2       | System Collection Sync          | 5       | 2       | 3   |
| 3       | Path Sync Coverage              | 8       | 0       | 0   |
| 4       | Indexer Routing in Sync         | 9       | 1       | 1   |
| 5       | Extension Maps Purpose          | 1       | 1       | 5   |
| 6       | Two-Pass Duplicate Prevention   | 2       | 2       | 0   |
| 7       | Indexing Status File Count      | 5       | 1       | 0   |
| 8       | File Count Remaining in API     | 1       | 2       | 0   |
| 9       | Thread Safety of Indexing        | 4       | 3       | 2   |
| 10      | Stale Entry Detection           | 6       | 0       | 2   |
| 11      | Search Efficiency               | 3       | 3       | 3   |
| 12      | N+1 Pattern (Informational)     | 1       | 2       | 0   |
| 13      | Query Escaping                  | 8       | 2       | 1   |
| 14      | Config Thread Safety            | 6       | 2       | 2   |
| 15      | DocStore/Debounce Thread Safety | 3       | 4       | 0   |
| 16      | Hash Consolidation              | 3       | 0       | 0   |
| 17      | Docstring Improvement           | 5       | 1       | 0   |
| **Total** |                               | **75**  | **27**  | **21** |

---

### Section 1: TLS Security

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Auto-generate CA and server certs | COVERED | test_tls::TestEnsureTLSCerts::test_generates_all_four_files, test_private_key_permissions | |
| 2 | Server cert includes required SANs | COVERED | test_tls::test_server_san_includes_localhost, _127_0_0_1, _docker_internal | |
| 3 | Server cert signed by CA | COVERED | test_tls::test_server_signed_by_ca, test_client_verifies_with_ca | |
| 4 | Auto-renew expired cert | COVERED | test_tls::test_expired_server_cert_is_regenerated | |
| 5 | Warn on near-expiry | COVERED | test_tls::test_near_expiry_logs_warning | |
| 6 | SSE serves over HTTPS | **GAP** | — | No test that `--sse` configures uvicorn with ssl_certfile/ssl_keyfile |
| 7 | Token auth requires TLS | **GAP** | — | No test for Bearer tokens over encrypted connection (integration-level) |
| 8 | CA cert available for client trust | PARTIAL | test_tls::test_client_verifies_with_ca | Missing: `mcp-config` CLI output includes ca_cert path |

### Section 2: System Collection Sync

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Sync enabled system collections | COVERED | test_sync::test_submits_system_collections | |
| 2 | Skip disabled collections | COVERED | test_sync::test_skips_disabled_collections | |
| 3 | Startup sync in background thread | PARTIAL | test_sync::test_done_event_is_set_after_sync | Missing: thread name "startup-sync", daemon flag |
| 4 | Detect email DB changes | COVERED | test_system_watcher::test_submits_job_on_change | |
| 5 | Detect calibre DB changes | COVERED | test_system_watcher::test_maps_path_to_correct_collection | |
| 6 | Detect RSS DB changes | PARTIAL | test_system_watcher::test_collects_db_paths_from_config | No explicit RSS change -> job submission test |
| 7 | Debounce rapid changes | COVERED | test_system_watcher::test_debounces_rapid_changes | |
| 8 | Monitoring starts after sync | **GAP** | — | No test for done_event ordering (watcher waits for sync) |
| 9 | Re-index handles new entries | **GAP** | — | No incremental re-index test for new entries in system DBs |
| 10 | Re-index handles deletions | **GAP** | — | No pruning test for deleted entries from system DB re-index |

### Section 3: Path Sync Coverage

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Sync home user directories | COVERED | test_sync::test_submits_home_directories | |
| 2 | Skip non-existent user dirs | COVERED | test_auto_indexer::test_only_returns_dirs_for_configured_users | |
| 3 | Sync global paths | COVERED | test_sync::test_submits_global_paths | |
| 4 | Sync obsidian vaults | COVERED | test_sync::test_submits_obsidian_vaults | |
| 5 | Sync code groups | COVERED | test_sync::test_submits_code_groups | |
| 6 | Auto-detect obsidian (.obsidian) | COVERED | test_auto_indexer::test_detects_obsidian_vault | |
| 7 | Auto-detect git repo (.git) | COVERED | test_auto_indexer::test_detects_git_repo | |
| 8 | Default to project type | COVERED | test_auto_indexer::test_defaults_to_project | |

### Section 4: Indexer Routing in Sync

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1a-f | Route all 6 indexer types | COVERED | test_indexing_queue::TestProcessRouter::test_routes_{obsidian,code,project,email,calibre,rss} | |
| 2 | Reject unknown type | COVERED | test_indexing_queue::test_unknown_indexer_type_raises | |
| 3 | File routing: obsidian marker | COVERED | test_sync::test_file_deep_in_obsidian_vault_uses_obsidian_indexer | |
| 4 | File routing: git marker | COVERED | test_sync::test_file_deep_in_git_repo_uses_code_indexer | |
| 5 | File routing: no markers | COVERED | test_sync::test_existing_file_submits_directory_job | |
| 6 | Prune job for deleted file | COVERED | test_sync::test_deleted_file_submits_prune_job | |
| 7 | Ignore unmapped file | PARTIAL | test_sync::test_unmapped_file_does_not_submit | Missing: warning log assertion |
| 8 | Ignore disabled collection | **GAP** | — | submit_file_change with disabled collection untested (code at sync.py:235) |

### Section 5: Extension Maps

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | _EXTENSION_MAP filters indexable files | PARTIAL | test_project_indexer::test_unknown_extensions_are_not_supported | Missing: _collect_files integration test showing files skipped |
| 2 | _EXTENSION_MAP provides source_type | COVERED | test_project_indexer::TestExtensionMap | |
| 3 | Obsidian uses _EXTENSION_MAP | **GAP** | — | No ObsidianIndexer attachment filtering test (.xyz skipped, .pdf included) |
| 4 | _CODE_EXTENSION_MAP for tree-sitter | **GAP** | — | No test for code file selection via _CODE_EXTENSION_MAP |
| 5 | _CODE_EXTENSION_MAP language names | **GAP** | — | No test for get_language_for_file returning correct language |
| 6 | Watcher triggers for supported ext | **GAP** | — | No file watcher extension filtering test |
| 7 | Watcher ignores unsupported ext | **GAP** | — | No file watcher extension filtering test |

### Section 6: Two-Pass Duplicate Prevention

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Vault files not re-indexed as leftovers | PARTIAL | test_project_indexer, test_discovery::TestLeftoverFiles | Missing: end-to-end ProjectIndexer.index() no-duplicate assertion |
| 2 | Git repo files not re-indexed | PARTIAL | test_project_indexer::test_code_files_not_double_indexed_in_doc_pass | Missing: leftover exclusion at ProjectIndexer level |
| 3 | Leftovers exclude claimed subtrees | COVERED | test_discovery::TestLeftoverFiles | |
| 4 | Upsert prevents duplicates | COVERED | test_base::test_two_pass_indexing_no_duplicates | |

### Section 7: Indexing Status File Count

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | File-level tracking | COVERED | test_indexing_status::test_set_file_total_and_processed | |
| 2 | File-level takes precedence | COVERED | test_indexing_status::test_file_counts_replace_job_counts | |
| 3 | Job-level shows integer | COVERED | test_indexing_status::test_increment_default_count | |
| 4 | Total remaining aggregates | PARTIAL | test_indexing_status::test_increment_multiple_collections | Missing: mixed file+job level aggregation |
| 5 | Idle returns None | COVERED | test_indexing_status::test_to_dict_returns_none_when_idle | |
| 6 | Collections removed when complete | COVERED | test_indexing_status::test_decrement_to_zero_removes | |

### Section 8: File Count Remaining in API

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Search response includes status | PARTIAL | test_mcp_server::test_includes_indexing_when_active | Missing: file-level dict shape with per-collection remaining |
| 2 | Search response omits when idle | COVERED | test_mcp_server::test_indexing_null_when_idle | |
| 3 | List collections includes status | PARTIAL | test_mcp_server::TestBuildListResponse::test_includes_indexing_when_active | Missing: file-level dict shape |

### Section 9: Thread Safety of Indexing

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Single-writer design | PARTIAL | test_indexing_queue::test_worker_processes_jobs | Architectural, not explicitly tested |
| 2 | Concurrent submission safe | **GAP** | — | No multi-threaded concurrent submit test |
| 3 | submit_and_wait blocks | COVERED | test_indexing_queue::test_blocks_until_job_completes | |
| 4 | submit_and_wait timeout | COVERED | test_indexing_queue::test_timeout_returns_none | |
| 5 | Graceful shutdown | PARTIAL | test_indexing_queue::test_shutdown_sends_sentinel | Missing: in-flight job completion assertion |
| 6 | Shutdown sentinel | COVERED | test_indexing_queue::test_shutdown_sends_sentinel | |
| 7 | DocStore single-thread access | **GAP** | — | Architectural invariant, no thread-identity assertion |
| 8 | Worker continues after exception | COVERED | test_indexing_queue::test_worker_handles_exceptions | |
| 9 | Done event set on failure | PARTIAL | test_indexing_queue::test_worker_handles_exceptions | Missing: submit_and_wait with failing job -> done event set, result=None |

### Section 10: Stale Entry Detection

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Deleted file -> stale | COVERED | test_search::test_marks_missing_file_as_stale | |
| 2 | Modified file -> stale | COVERED | test_search::test_marks_modified_file_as_stale | |
| 3 | Unchanged -> not stale | COVERED | test_search::test_fresh_file_not_stale | |
| 4 | Skip non-filesystem sources | COVERED | test_search::test_non_file_path_not_marked_stale, test_rss_url | |
| 5 | Stat cache deduplication | **GAP** | — | No test asserting os.stat called once for multi-chunk same file |
| 6 | Stale flag in API response | COVERED | test_mcp_server::test_result_dict_includes_stale_field | |
| 7 | PermissionError handling | **GAP** | — | No test for PermissionError -> stale=True |
| 8 | Missing file_modified_at | COVERED | test_search::test_no_file_modified_at_not_stale | |

### Section 11: Search Efficiency

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Batch metadata loading | COVERED | test_search::TestBatchLoadMetadata | |
| 2 | Cache shared between vec+FTS | COVERED | test_search::TestMetadataCache | |
| 3 | Cache prevents redundant RRF loads | PARTIAL | test_search::test_cache_partial_hit | Missing: full pipeline verification |
| 4 | Unfiltered oversampling (3x) | **GAP** | — | No _candidate_limit unit test |
| 5 | Filtered oversampling (50x) | **GAP** | — | No _candidate_limit unit test |
| 6 | Early termination at top_k | **GAP** | — | No test proving _apply_filters stops early |
| 7 | Empty visible_collections | COVERED | test_search::test_visible_collections_empty | |
| 8 | Empty FTS query short-circuit | PARTIAL | test_search_utils::test_empty_query, test_whitespace_only | Missing: _fts_search no-execute verification |

### Section 12: N+1 Pattern (Informational)

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Anti-pattern example | N/A | — | Informational |
| 2 | Batch loading avoids N+1 | COVERED | test_search::TestBatchLoadMetadata | |
| 3 | Pruning uses batch query | PARTIAL | test_base_indexer::TestPruneStaleSources | Missing: query count assertion |
| 4 | Delete uses batch ops | PARTIAL | test_base_indexer::TestDeleteSource | Missing: query count assertion |

### Section 13: Query Escaping

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Normal query wrapped in quotes | COVERED | test_search_utils::test_simple_query_wrapped_as_phrase | |
| 2 | Embedded quotes doubled | COVERED | test_search_utils::test_internal_double_quotes_doubled | |
| 3 | FTS operators neutralized | COVERED | test_search_utils::test_fts_operators_escaped | |
| 4 | Whitespace-only -> empty | COVERED | test_search_utils::test_whitespace_only_returns_empty | |
| 5 | Empty -> empty | COVERED | test_search_utils::test_empty_query_returns_empty | |
| 6 | Special FTS5 chars handled | COVERED | test_search_utils::test_asterisk_escaped, test_caret_escaped | |
| 7 | All FTS paths use escape | PARTIAL | — | No structural assertion that _fts_search calls escape_fts_query |
| 8 | FTS failure handled | **GAP** | — | No test for _fts_search catching OperationalError -> empty list + warning |
| 9 | SQL parameterized placeholders | COVERED | Enforced by ruff S608 + CI | |
| 10 | Ruff S608 enabled | COVERED | pyproject.toml extend-select | |

### Section 14: Config Thread Safety

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Config frozen (immutable) | COVERED | test_config::test_config_is_frozen | |
| 2 | with_overrides returns new instance | COVERED | test_config::test_with_overrides_returns_new_instance + 4 related tests | |
| 3 | Config reads thread-safe | COVERED | test_config_watcher::test_get_config_is_thread_safe | |
| 4 | Config replacement atomic | COVERED | test_config_watcher::test_reload_updates_config | |
| 5 | Invalid config preserves current | COVERED | test_config_watcher::test_reload_preserves_old_config_on_parse_error | |
| 6 | Config reload updates queue | PARTIAL | test_config_watcher::test_callback_receives_new_config | Missing: integration test for on_reload -> indexing_queue.set_config() |
| 7 | Worker reads fresh config per job | PARTIAL | test_indexing_queue::test_set_config_replaces_config | Missing: worker uses new config on next job |
| 8 | Adding collection triggers sync | **GAP** | — | No integration test: config reload -> new indexing jobs submitted |
| 9 | Disabling collection stops indexing | **GAP** | — | No integration test: config reload -> disabled collection skipped |
| 10 | Debounce prevents rapid reloads | COVERED | test_config_watcher::test_debounces_rapid_changes | |

### Section 15: DocStore/Debounce Thread Safety

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | DocStore single-writer design | PARTIAL | — | Architectural, enforced by code structure, no explicit thread-identity test |
| 2 | DocStore WAL mode | COVERED | test_doc_store::test_enables_wal_mode | |
| 3 | DocStore busy_timeout | COVERED | test_doc_store::test_busy_timeout_is_set | |
| 4 | Debounce timer reset on change | COVERED | test_system_watcher::test_debounces_rapid_changes | |
| 5 | Debounce timer state locked | PARTIAL | test_system_watcher::test_debounces_rapid_changes | No true multi-threaded concurrent notify_change stress test |
| 6 | Stop flushes pending changes | COVERED | test_system_watcher::test_stop_flushes_pending | |
| 7 | ConfigWatcher debounce thread-safe | PARTIAL | test_config_watcher::test_debounces_rapid_changes, test_stop_cancels_pending_timer | No true multi-threaded concurrent notify_change stress test |

### Section 16: Hash Consolidation

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | file_hash defined in one module | COVERED | Verified: indexers/base.py line 19 only definition | |
| 2 | doc_store.py imports from base | COVERED | Verified: doc_store.py line 14 imports from indexers.base | |
| 3 | Consistent SHA-256 output | COVERED | test_base::TestFileHash::test_returns_sha256_hex, test_same_content, test_different_content | |

### Section 17: Docstring Improvement

| # | Scenario | Status | Existing Test(s) | Gap |
|---|----------|--------|-------------------|-----|
| 1 | Concise one-line summary | COVERED | Verified: mcp_server.py line 310 | |
| 2 | Summary separated by blank line | COVERED | Verified: line 311 is blank | |
| 3 | Args documents all parameters | COVERED | Verified: lines 394-408 | |
| 4 | Returns documents return type | COVERED | Verified: lines 406-409 | |
| 5 | Extended description dual purpose | COVERED | Verified: lines 312-392 | |
| 6 | No redundancy | PARTIAL | — | Minor overlap between examples and Args for filter descriptions |

---

### Priority 1 — Missing Tests (GAPs)

Tests that do not exist and cover behavioral requirements.

| # | Section | Scenario | What to Test |
|---|---------|----------|--------------|
| 1 | S1.6 | SSE serves over HTTPS | `--sse` configures uvicorn with ssl_certfile/ssl_keyfile |
| 2 | S1.7 | Token auth requires TLS | Bearer tokens transmitted over encrypted connection (integration) |
| 3 | S2.8 | Monitoring starts after sync | System watcher waits for startup sync done_event before starting |
| 4 | S2.9 | Re-index new entries | Incremental re-index adds new entries, skips unchanged |
| 5 | S2.10 | Re-index deletions | Re-index prunes entries for deleted items from system DBs |
| 6 | S4.8 | Ignore disabled collection | submit_file_change returns without submitting for disabled collection |
| 7 | S5.3 | Obsidian attachment filtering | ObsidianIndexer indexes .pdf/.png but skips .xyz via _EXTENSION_MAP |
| 8 | S5.4 | Code file selection | _CODE_EXTENSION_MAP controls which files get tree-sitter parsing |
| 9 | S5.5 | Language name lookup | get_language_for_file returns correct language from _CODE_EXTENSION_MAP |
| 10 | S5.6-7 | Watcher extension filter | File watcher emits events only for supported extensions |
| 11 | S9.2 | Concurrent submission | 10+ threads calling submit() simultaneously, all jobs processed |
| 12 | S10.5 | Stat cache dedup | os.stat called once for 5 results from same source file |
| 13 | S10.7 | PermissionError -> stale | Mock os.stat raising PermissionError, verify stale=True |
| 14 | S11.4-5 | Oversampling factors | _candidate_limit returns top_k*3 (unfiltered) and top_k*50 (filtered) |
| 15 | S11.6 | Early termination | _apply_filters stops iterating after top_k matches found |
| 16 | S13.8 | FTS failure handling | _fts_search catches OperationalError, returns [], logs warning |
| 17 | S14.8 | New collection triggers sync | Config reload with new vault -> indexing jobs submitted |
| 18 | S14.9 | Disabled collection stops indexing | Config reload with disabled collection -> sync and watcher skip it |

### Priority 2 — Partial Coverage Enhancements

Tests that exist but need additional assertions or cases.

| # | Section | Scenario | What to Add |
|---|---------|----------|-------------|
| 1 | S1.8 | CA cert for client trust | Test `mcp-config` CLI output includes ca_cert path |
| 2 | S2.3 | Startup sync thread | Assert thread name "startup-sync" and daemon=True |
| 3 | S4.7 | Unmapped file warning | Add caplog assertion for warning when file is unmapped |
| 4 | S6.1-2 | Two-pass no duplicates | End-to-end ProjectIndexer.index() with vault+leftovers, assert no file indexed twice |
| 5 | S7.4 | Mixed aggregation | Test total_remaining with both file-level and job-level counts |
| 6 | S8.1 | Search response status | Test with file-level status showing per-collection {total, processed, remaining} |
| 7 | S8.3 | List response status | Same file-level dict shape test for list collections response |
| 8 | S9.1 | Single-writer design | Assert no concurrent DB writes (architectural, may be impractical) |
| 9 | S9.5 | Graceful shutdown | Start long-running job, call shutdown(), verify job completed |
| 10 | S9.9 | Done event on failure | submit_and_wait with failing job: verify caller unblocks, result=None |
| 11 | S11.3 | Cache full pipeline | Run full search(), verify metadata_cache used end-to-end through RRF |
| 12 | S11.8 | FTS empty short-circuit | Call _fts_search with empty query, mock DB to verify no execute() |
| 13 | S14.6 | Config -> queue wiring | Integration test: on_reload callback calls indexing_queue.set_config() |
| 14 | S14.7 | Worker uses fresh config | After set_config, verify next job sees new config |
| 15 | S15.5 | Concurrent debounce | Multi-threaded notify_change stress test for SystemCollectionWatcher |
| 16 | S15.7 | Concurrent config debounce | Multi-threaded notify_change stress test for ConfigWatcher |
