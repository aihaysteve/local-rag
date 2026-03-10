# Ollama Setup and Embedding Model

How local-rag uses Ollama to generate embeddings, what the bge-m3 model does, and how to set everything up.

## What Is Ollama?

Ollama runs machine learning models locally on your Mac. It works like a local API server — accepts text over HTTP, returns results. Nothing leaves your machine.

It listens on `http://localhost:11434`. local-rag sends text to it and gets back numerical representations (embeddings).

### Installation

```bash
brew install ollama
```

After installation, Ollama runs automatically as a background service on macOS. You can verify it's running:

```bash
curl http://localhost:11434
# Should return: "Ollama is running"
```

If it's not running, start it manually:

```bash
ollama serve
```

## What Are Embeddings?

An embedding is a list of numbers (a vector) representing the meaning of a piece of text. Similar texts produce vectors close together; unrelated texts produce vectors far apart.

For example, the bge-m3 model converts text into a vector of 1024 floating-point numbers:

```shell
"kubernetes deployment" → [0.023, -0.156, 0.891, ..., 0.042]  (1024 numbers)
"k8s rollout strategy"  → [0.019, -0.148, 0.887, ..., 0.039]  (1024 numbers, very similar)
"chocolate cake recipe"  → [-0.412, 0.733, -0.024, ..., 0.518]  (1024 numbers, very different)
```

These vectors enable semantic search: instead of matching exact words, we compare vector proximity. A search for "kubernetes deployment" finds a document titled "k8s rollout strategy" even though the words differ.

### How Vectors Are Compared

local-rag uses cosine distance to measure vector similarity. Cosine distance measures the angle between two vectors: identical vectors have distance 0, unrelated vectors approach 2. The sqlite-vec extension performs this comparison efficiently across thousands of stored vectors.

## The bge-m3 Model

local-rag uses **bge-m3** as its default embedding model:

| Property            | Value                                                                     |
|---------------------|---------------------------------------------------------------------------|
| Full name           | BAAI General Embedding - Multi-Function, Multi-Lingual, Multi-Granularity |
| Developed by        | Beijing Academy of Artificial Intelligence (BAAI)                         |
| Vector dimensions   | 1024                                                                      |
| Supported languages | 100+ (English, German, Chinese, Japanese, etc.)                           |
| Download size       | ~1.2 GB                                                                   |
| RAM usage           | ~2 GB when loaded                                                         |

### Why bge-m3?

- **Quality**: Ranks among the top open-source embedding models on retrieval benchmarks (MTEB).
- **Multilingual**: Handles mixed-language notes and emails natively. A German document about "Kubernetes-Bereitstellung" matches an English query about "kubernetes deployment".
- **Runs locally**: Fits comfortably in memory on any modern Mac.
- **1024 dimensions**: Balances quality and storage. Each document chunk requires 4 KB of vector storage (1024 floats x 4 bytes).

### Pulling the Model

Before first use, download the model:

```bash
ollama pull bge-m3
```

This downloads ~1.2 GB. The model is cached locally and downloaded only once.

Verify it's available:

```bash
ollama list
# Should show bge-m3 in the output
```

### First Request Latency

After a restart, Ollama loads the model into memory on the first request. This takes 10-30 seconds depending on hardware. Subsequent requests complete in milliseconds. local-rag uses a 5-minute timeout per request to account for this cold start.

## How local-rag Uses Ollama

### During Indexing

When you index documents, local-rag:

1. Parses each document into text
2. Splits the text into chunks (~500 tokens each)
3. Sends chunks to Ollama in batches of 32
4. Gets back a 1024-dimensional vector for each chunk
5. Stores the vectors in SQLite via the sqlite-vec extension

The batch size of 32 balances throughput and memory. A vault of 1,000 notes producing 5,000 chunks sends ~156 batches to Ollama.

### During Search

When you run a search query, local-rag:

1. Sends your query text to Ollama to get a single embedding vector
2. Uses sqlite-vec to find the stored vectors closest to your query vector
3. Combines these results with keyword search results using RRF (see [hybrid-search-and-rrf.md](hybrid-search-and-rrf.md))

Every search requires one Ollama call to embed the query.

### Vector Storage Format

Embeddings are stored in SQLite as packed binary blobs — each float serialized as 4 bytes in IEEE 754 format via Python's `struct.pack`. The sqlite-vec extension reads this format directly for fast comparison.

```shell
1024 floats × 4 bytes = 4,096 bytes per document chunk
```

For 10,000 indexed chunks, the vector data alone takes ~40 MB of database space.

## Using a Remote Ollama Server

If you have a machine with a better GPU (e.g., a desktop with an RTX card), run Ollama there and point ragling at it from your laptop.

### Setup

On the remote machine, install Ollama and pull the embedding model:

```bash
brew install ollama    # or see https://ollama.com for Linux
ollama pull bge-m3
```

Ollama binds to localhost by default. To accept remote connections, set the host before starting:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

### Configuration

In `~/.ragling/config.json` on the machine running ragling:

```json
{
  "ollama_host": "http://gpu-box:11434",
  "embedding_model": "bge-m3",
  "embedding_dimensions": 1024
}
```

When set, ragling connects to that URL for all embedding operations. When omitted (or `null`), ragling falls back to the `OLLAMA_HOST` environment variable, then `http://127.0.0.1:11434`.

### Network considerations

Embedding requests are batched (32 texts per request). On a local network this adds negligible latency. Over higher-latency connections, indexing slows but search (one embedding call per query) is barely affected.

Make sure the embedding model name and dimensions in your config match what's available on the remote Ollama instance.

## Using a Different Model

Configure the embedding model in `~/.local-rag/config.json`:

```json
{
  "embedding_model": "bge-m3",
  "embedding_dimensions": 1024
}
```

Other compatible models you could use:

| Model             | Dimensions | Size    | Notes                                 |
|-------------------|------------|---------|---------------------------------------|
| bge-m3 (default)  | 1024       | ~1.2 GB | Best multilingual, recommended        |
| mxbai-embed-large | 1024       | ~670 MB | Good English-focused alternative      |
| nomic-embed-text  | 768        | ~270 MB | Smaller, faster, decent quality       |
| all-minilm        | 384        | ~45 MB  | Minimal resource usage, lower quality |

To switch models:

1. Pull the new model: `ollama pull <model-name>`
2. Update `config.json` with the new model name and dimensions
3. **Re-index everything** — embeddings from different models are incompatible

```bash
uv run local-rag index obsidian --force
uv run local-rag index email --force
uv run local-rag index calibre --force
uv run local-rag index rss --force
uv run local-rag index repo --force
# Repeat for any project collections as well
```

Re-indexing is required because each model encodes meaning differently. Vectors from bge-m3 and nomic-embed-text can't be compared — they occupy different mathematical spaces.

## Troubleshooting

### "Cannot connect to Ollama. Is it running?"

Start Ollama:

```bash
ollama serve
```

Or check the service status:

```bash
brew services list | grep ollama
```

### Indexing is slow

- **First batch is slow**: Normal — Ollama is loading the model into memory.
- **All batches are slow**: Check if your Mac is under memory pressure (`Activity Monitor` > Memory). bge-m3 needs ~2 GB of free RAM.
- **On Apple Silicon**: Ollama uses the GPU automatically. On Intel Macs, it runs on CPU which is significantly slower.

### Model not found

```bash
ollama pull bge-m3
```

Make sure the model name in your config matches exactly what Ollama shows in `ollama list`.
