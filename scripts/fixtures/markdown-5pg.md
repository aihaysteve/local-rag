# Meridian: A Distributed Document Processing Platform

**Version 3.2 — Architecture Reference**

Meridian is a distributed document processing platform designed for
organizations that need to ingest, transform, and serve large volumes
of heterogeneous documents with low latency and high reliability.

---

## 1. System Overview

Meridian follows an event-driven microservices architecture. Documents
enter the system through one of several ingestion adapters, flow through
a processing pipeline, and are stored in a content-addressed document
store. Downstream consumers access processed documents through a
query API that supports full-text search, semantic search, and
structured metadata filtering.

The system is designed around three core principles:

- **Idempotency**: Every operation can be safely retried without
  side effects. Document processing uses content-based hashing to
  detect duplicates at every stage.
- **Horizontal scalability**: Each service can be independently
  scaled based on workload. The processing pipeline uses a task
  queue with configurable concurrency.
- **Local-first operation**: The entire system runs on commodity
  hardware without requiring cloud services or external APIs.

### 1.1 Design Goals

Meridian was designed to address several shortcomings observed in
existing document processing systems. Many commercial solutions require
cloud connectivity, which creates data sovereignty concerns for
organizations handling sensitive materials. Open-source alternatives
often lack the robustness needed for production workloads, particularly
around error handling, retry logic, and monitoring.

The primary design goals are:

1. Process documents of any supported format within 30 seconds of ingestion
2. Maintain a content-addressed cache that eliminates redundant processing
3. Support concurrent access from multiple downstream consumers
4. Provide clear operational visibility through structured logging and metrics
5. Run entirely on local infrastructure with no external dependencies

### 1.2 Supported Document Formats

Meridian supports a wide range of document formats through pluggable
parser modules. Each parser implements a common interface that accepts
raw bytes and produces a structured document representation.

| Format   | Parser Module     | Features                          |
|----------|-------------------|-----------------------------------|
| PDF      | `meridian.pdf`    | Text extraction, table detection  |
| DOCX     | `meridian.docx`   | Full formatting preservation      |
| PPTX     | `meridian.pptx`   | Slide text and speaker notes      |
| Markdown | `meridian.md`     | CommonMark with extensions        |
| HTML     | `meridian.html`   | Boilerplate removal, main content |
| EPUB     | `meridian.epub`   | Chapter segmentation              |
| Audio    | `meridian.audio`  | Speech-to-text via Whisper        |
| Image    | `meridian.image`  | OCR and visual description        |

---

## 2. Ingestion Layer

The ingestion layer is responsible for accepting documents from external
sources and placing them into the processing pipeline. It consists of
several adapter modules, each tailored to a specific source type.

### 2.1 File System Watcher

The file system watcher monitors one or more directories for new or
modified files. It uses inotify on Linux and FSEvents on macOS to
receive real-time notifications. When a change is detected, the watcher
computes a SHA-256 hash of the file contents and checks the document
store for an existing entry. If the hash is new, the file is enqueued
for processing.

The watcher supports recursive directory monitoring and configurable
file extension filters. A debounce mechanism prevents duplicate events
when editors save files by writing to a temporary location and then
renaming.

```python
class FileSystemWatcher:
    """Monitors directories for new or modified files."""

    def __init__(
        self,
        directories: list[Path],
        extensions: set[str] | None = None,
        debounce_ms: int = 500,
    ) -> None:
        self.directories = directories
        self.extensions = extensions or {".pdf", ".docx", ".md", ".txt"}
        self.debounce_ms = debounce_ms
        self._seen_hashes: dict[Path, str] = {}

    def on_file_changed(self, path: Path) -> None:
        """Called when a file is created or modified."""
        content_hash = compute_sha256(path)
        if self._seen_hashes.get(path) == content_hash:
            return  # No actual content change
        self._seen_hashes[path] = content_hash
        self.enqueue(path, content_hash)

    def enqueue(self, path: Path, content_hash: str) -> None:
        """Place a file into the processing queue."""
        task = IngestionTask(
            source_path=path,
            content_hash=content_hash,
            timestamp=datetime.now(tz=UTC),
        )
        self.queue.put(task)
```

### 2.2 Database Connector

The database connector reads documents from external SQLite databases
in read-only mode. This is used for integrating with applications that
store content in local databases, such as email clients, RSS readers,
and note-taking applications.

The connector uses WAL mode for concurrent read access and implements
incremental synchronization by tracking the maximum row ID or timestamp
seen in previous runs. Each run queries only for rows added since the
last synchronization point.

### 2.3 API Endpoint

For programmatic ingestion, Meridian exposes a simple HTTP endpoint
that accepts document uploads. The endpoint validates the content type,
computes the hash, and enqueues the document. It returns immediately
with a task ID that clients can use to poll for processing status.

---

## 3. Processing Pipeline

The processing pipeline transforms raw documents into structured
representations suitable for storage and retrieval. It operates as
a directed acyclic graph of processing stages, where each stage
reads from an input queue and writes to an output queue.

### 3.1 Document Parsing

The first stage extracts structured content from raw document bytes.
Each parser module produces a `ParsedDocument` containing the document
text, metadata (title, author, creation date), and structural
information (headings, paragraphs, tables, lists).

Parsing is the most format-dependent stage. PDF parsing, for example,
must handle both text-based and scanned documents. For scanned pages,
the parser falls back to OCR using Tesseract. Table detection uses
a combination of rule-based heuristics and a lightweight neural
model trained on document layouts.

### 3.2 Chunking

After parsing, documents are split into chunks suitable for embedding
and retrieval. The chunking strategy balances several competing
objectives:

- Chunks should be small enough to produce focused embeddings
- Chunks should be large enough to preserve semantic coherence
- Chunk boundaries should respect document structure (headings, paragraphs)
- Overlap between adjacent chunks helps maintain context

Meridian uses a hierarchical chunking approach:

1. **Section splitting**: The document is first divided at heading boundaries
2. **Paragraph splitting**: Large sections are further divided at paragraph breaks
3. **Token-based splitting**: Any remaining oversized chunks are split at the
   nearest sentence boundary that keeps the chunk below the token limit
4. **Overlap injection**: The last N tokens of each chunk are prepended to the
   next chunk to provide continuity

The default configuration uses 256 tokens per chunk with 50 tokens of
overlap, though these values are configurable per collection.

### 3.3 Enrichment

The enrichment stage enhances chunks with additional information that
improves retrieval quality. Several enrichment modules are available:

- **Code annotation**: Identifies programming language, extracts function
  signatures, and adds semantic labels to code blocks
- **Formula rendering**: Converts LaTeX formulas to descriptive text
  that can be meaningfully embedded
- **Image description**: Generates natural language descriptions of
  embedded images using a local vision-language model
- **Table linearization**: Converts tabular data into natural language
  statements that capture the relationships between cells

Each enrichment module is optional and can be enabled or disabled per
configuration profile. The "fast" profile disables all enrichments
for maximum throughput, while the "quality" profile enables everything
at the cost of processing time.

### 3.4 Embedding

The final pipeline stage computes vector embeddings for each chunk.
Meridian supports multiple embedding models through a unified interface:

- **nomic-embed-text**: Fast, lightweight, good for general text.
  384-dimensional vectors with a context window of 8,192 tokens.
- **bge-m3**: Higher quality, multilingual support, hybrid retrieval
  capabilities. 1,024-dimensional vectors with excellent performance
  on benchmarks. Supports dense, sparse, and ColBERT-style retrieval.

Embeddings are computed locally using Ollama as the inference backend.
Batch processing groups chunks by size to maximize GPU utilization.
A caching layer prevents re-embedding chunks that have already been
processed with the same model.

---

## 4. Storage Layer

### 4.1 Document Store

The document store is a content-addressed SQLite database. Each entry
is keyed by the SHA-256 hash of the original document content. The
store holds the parsed document representation, extracted metadata,
and chunk boundaries.

Using content addressing provides natural deduplication. If the same
document is ingested through multiple adapters or at different times,
it is stored only once. The store uses WAL mode to support concurrent
reads from multiple consumers without blocking writes.

The schema includes the following tables:

- `documents`: Hash, source path, format, parse timestamp, raw metadata
- `chunks`: Document hash, chunk index, text content, token count
- `embeddings`: Chunk ID, model name, vector blob
- `processing_log`: Task ID, stage, status, duration, error message

### 4.2 Vector Index

Each consumer group maintains its own vector index built from the
shared document store. This per-group isolation allows different
groups to use different embedding models, chunk sizes, or subsets
of the document corpus without interfering with each other.

The vector index uses HNSW (Hierarchical Navigable Small World)
graphs for approximate nearest neighbor search. Index parameters
are tuned based on the collection size:

- Small collections (under 10,000 chunks): `ef_construction=200`, `M=16`
- Medium collections (10,000 to 100,000 chunks): `ef_construction=400`, `M=32`
- Large collections (over 100,000 chunks): `ef_construction=600`, `M=48`

### 4.3 Full-Text Search Index

In addition to vector search, Meridian maintains a full-text search
index using SQLite FTS5. This enables keyword-based retrieval that
complements semantic search. The hybrid search implementation combines
vector similarity scores with BM25 text scores using Reciprocal Rank
Fusion (RRF).

The RRF formula is:

    score(d) = sum over r in rankings of: 1 / (k + rank_r(d))

where k is a constant (default 60) that controls the influence of
individual rankings. Documents that rank highly in both vector and
keyword search receive the highest combined scores.

---

## 5. Query API

The query API provides a unified interface for searching processed
documents. It supports three retrieval modes:

- **Semantic search**: Embeds the query and finds similar chunks by
  vector distance
- **Keyword search**: Uses FTS5 for traditional text matching
- **Hybrid search**: Combines both approaches using RRF

### 5.1 Query Processing

Incoming queries go through several preprocessing steps before
retrieval:

1. Query text is normalized (lowercased, whitespace collapsed)
2. For semantic search, the query is embedded using the same model
   as the target collection
3. For keyword search, the query is tokenized and stop words are removed
4. Results from both paths are merged using RRF
5. A configurable reranking step can optionally rescore the top N
   results using a cross-encoder model

### 5.2 Filtering and Faceting

Queries can be filtered by document metadata including source path,
file format, date range, and custom tags. Filters are applied before
retrieval to reduce the search space and improve performance.

Faceted search returns aggregated counts for metadata fields alongside
search results. This helps consumers understand the distribution of
results across different document sources and time periods.

### 5.3 Response Format

Search results are returned as a list of scored chunks with full
provenance information:

- Chunk text and surrounding context
- Source document path and metadata
- Chunk position within the document
- Similarity score and ranking method
- Processing timestamp and model version

---

## 6. Operational Concerns

### 6.1 Monitoring and Logging

Meridian uses structured JSON logging throughout. Each log entry
includes a timestamp, service name, log level, and a structured
payload with context-specific fields. Processing stages log their
input hash, output hash, duration, and any errors encountered.

Key metrics are exposed for monitoring:

- Documents processed per minute
- Average processing latency by stage
- Queue depth and consumer lag
- Cache hit rates for parsing, embedding, and search
- Error rates by document format and processing stage

### 6.2 Error Handling

Processing failures are handled at multiple levels. Individual
parser errors result in the affected document being marked as
failed with an error message in the processing log. The document
can be retried manually or will be reprocessed if a new version
of the parser is deployed.

Pipeline-level failures (queue unavailable, disk full) trigger
circuit breakers that pause processing and alert operators.
Recovery is automatic once the underlying issue is resolved.

### 6.3 Backup and Recovery

The SQLite databases that back the document store and vector indexes
can be backed up using standard filesystem tools. WAL mode ensures
that backups taken during operation are consistent. The
content-addressed design means that recovery from a partial backup
only requires re-indexing documents whose hashes are missing from
the restored store.

### 6.4 Performance Tuning

Several parameters affect system performance:

- **Worker concurrency**: Number of parallel processing tasks.
  Default is the number of CPU cores minus one.
- **Batch size**: Number of chunks embedded in a single model call.
  Larger batches improve GPU utilization but increase latency.
- **Cache size**: Maximum memory allocated for the LRU parse cache.
  Larger caches reduce disk I/O for frequently accessed documents.
- **Index rebuild threshold**: Number of new chunks before the HNSW
  index is rebuilt from scratch rather than incrementally updated.

---

## 7. Deployment

### 7.1 System Requirements

Meridian is designed to run on a single machine with the following
minimum specifications:

- 8 GB RAM (16 GB recommended for large collections)
- 4 CPU cores
- SSD storage for database files
- Optional GPU for accelerated embedding and ASR

### 7.2 Configuration

All configuration is managed through a single TOML file. Settings
are organized by subsystem:

```toml
[ingestion]
watch_dirs = ["~/Documents", "~/Projects"]
extensions = [".pdf", ".docx", ".md", ".txt", ".epub"]

[processing]
workers = 4
chunk_size_tokens = 256
chunk_overlap_tokens = 50

[embedding]
model = "bge-m3"
batch_size = 64
ollama_host = "http://localhost:11434"

[storage]
db_path = "~/.meridian/store.sqlite"
index_path = "~/.meridian/indexes/"

[search]
default_mode = "hybrid"
rrf_k = 60
rerank_top_n = 20
```

### 7.3 Installation

Meridian is distributed as a Python package and can be installed using
pip or uv. All dependencies are vendored or available from PyPI. The
embedding backend (Ollama) must be installed separately.

```bash
# Install Meridian
uv pip install meridian

# Pull embedding models
ollama pull nomic-embed-text
ollama pull bge-m3

# Initialize the database
meridian init

# Start the processing pipeline
meridian start --config meridian.toml
```

---

## Appendix A: Glossary

- **Chunk**: A segment of document text sized for embedding, typically
  128-512 tokens.
- **Content-addressed**: Storage where items are keyed by a hash of
  their content, providing natural deduplication.
- **Embedding**: A dense vector representation of text in a
  high-dimensional space where semantic similarity corresponds to
  geometric proximity.
- **HNSW**: Hierarchical Navigable Small World, a graph-based algorithm
  for approximate nearest neighbor search.
- **RRF**: Reciprocal Rank Fusion, a method for combining ranked lists
  from different retrieval systems.
- **WAL**: Write-Ahead Logging, a SQLite journaling mode that enables
  concurrent reads and writes.

## Appendix B: Changelog

- **v3.2**: Added audio ingestion via Whisper, image description
  enrichment, and configurable benchmark matrix.
- **v3.1**: Introduced hybrid search with RRF, per-group vector
  index isolation, and incremental indexing.
- **v3.0**: Complete rewrite with event-driven pipeline architecture,
  content-addressed document store, and pluggable parsers.
- **v2.x**: Monolithic architecture with PDF-only support.
- **v1.x**: Initial prototype, single-user, CLI only.
