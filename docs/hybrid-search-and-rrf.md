# Hybrid Search and Reciprocal Rank Fusion (RRF)

local-rag finds relevant documents using two search strategies and combines them into a single ranked list.

## The Problem with a Single Search Strategy

Text search has two fundamentally different approaches:

**Keyword search** finds documents containing the exact words you typed. Searching for "kubernetes deployment" returns documents with those words. It's fast and precise but misses synonyms and rephrasings. A document about "k8s rollout strategy" won't match, even though it's clearly relevant.

**Semantic search** converts your query and all stored documents into numerical vectors that represent their meaning, then finds documents whose vectors are closest to your query's vector. This catches synonyms and rephrasings but can miss documents containing the exact phrase you need — and sometimes returns thematically related but unhelpful results.

Neither approach alone gives reliably good results. Hybrid search runs both and merges them.

## How local-rag Runs a Search

When you search for "kubernetes deployment strategy", two searches run in parallel:

### 1. Vector Search (Semantic)

Ollama runs the bge-m3 model locally to convert your query into a 1024-dimensional vector — 1024 floating-point numbers encoding the query's meaning.

sqlite-vec, a SQLite extension for nearest-neighbor search, compares this vector against all stored document vectors and returns the closest matches ranked by cosine distance (lower = more similar).

The result is a ranked list like:

| Rank | Document                               | Why it matched  |
|------|----------------------------------------|-----------------|
| 1    | "K8s rollout best practices"           | Similar meaning |
| 2    | "Container orchestration guide"        | Related topic   |
| 3    | "Kubernetes deployment YAML reference" | Direct match    |

### 2. Full-Text Search (Keyword)

The same query is tokenized and matched against an FTS5 index (SQLite's built-in full-text search). FTS5 finds documents containing the literal words "kubernetes", "deployment", and "strategy", ranked by BM25 scoring.

The result is a different ranked list:

| Rank | Document                                  | Why it matched       |
|------|-------------------------------------------|----------------------|
| 1    | "Kubernetes deployment YAML reference"    | Contains exact words |
| 2    | "Kubernetes cluster deployment checklist" | Contains exact words |
| 3    | "Deployment strategy for microservices"   | Partial word match   |

Notice the two lists overlap but aren't identical. Each catches things the other misses.

## Combining Results with Reciprocal Rank Fusion

Now we have two ranked lists. How do we merge them?

Averaging raw scores fails because vector distances and FTS5 rank scores use different scales and distributions. A vector distance of 0.3 and an FTS rank of -12.5 aren't comparable.

**Reciprocal Rank Fusion (RRF)** solves this by ignoring raw scores and using only rank positions. If a document ranks highly in both lists, it ranks highly in the merged list. If it ranks highly in only one, it still appears but lower.

### The Formula

For each document, RRF computes:

```shell
rrf_score = vector_weight / (k + vector_rank) + fts_weight / (k + fts_rank)
```

Where:

- `vector_rank` is the document's position in the vector search results (1 = best match)
- `fts_rank` is the document's position in the FTS results (1 = best match)
- `k` is a smoothing constant (default: 60)
- `vector_weight` is how much to trust semantic search (default: 0.7)
- `fts_weight` is how much to trust keyword search (default: 0.3)

If a document only appears in one of the two lists, it only gets a score from that list (the other term is zero).

### Worked Example

Say we have these results:

**Vector search results:**

1. Doc A (k8s rollout best practices)
2. Doc B (container orchestration guide)
3. Doc C (kubernetes deployment YAML reference)

**FTS results:**

1. Doc C (kubernetes deployment YAML reference)
2. Doc D (kubernetes cluster deployment checklist)
3. Doc E (deployment strategy for microservices)

Using the defaults (`k=60`, `vector_weight=0.7`, `fts_weight=0.3`):

| Document | Vector Rank | FTS Rank | Vector Contribution   | FTS Contribution      | Total RRF Score |
|----------|-------------|----------|-----------------------|-----------------------|-----------------|
| Doc C    | 3           | 1        | 0.7 / (60+3) = 0.0111 | 0.3 / (60+1) = 0.0049 | **0.0160**      |
| Doc A    | 1           | —        | 0.7 / (60+1) = 0.0115 | 0                     | **0.0115**      |
| Doc B    | 2           | —        | 0.7 / (60+2) = 0.0113 | 0                     | **0.0113**      |
| Doc D    | —           | 2        | 0                     | 0.3 / (60+2) = 0.0048 | **0.0048**      |
| Doc E    | —           | 3        | 0                     | 0.3 / (60+3) = 0.0048 | **0.0048**      |

**Final ranking:** C, A, B, D, E

Doc C wins because it appeared in both lists — a strong signal that it's relevant both semantically and by keyword. Doc A ranks second because it was the top semantic match even though it didn't contain the exact keywords.

### Why k = 60?

The `k` parameter controls how much rank position matters. A higher `k` shrinks the gap between rank 1 and rank 5, making the formula more forgiving of lower-ranked results. A lower `k` gives top-ranked documents disproportionately more weight.

`k=60` is the standard value from the original RRF paper (Cormack et al., 2009). It works well across a wide range of datasets and rarely needs tuning.

### Why 0.7 / 0.3 Weights?

The default weights favor semantic search (0.7) over keyword search (0.3) because most queries are natural language questions where meaning matters more than exact words. If you primarily search for exact phrases or identifiers, increase `fts_weight` in the config.

These values are configurable in `~/.ragling/config.json`:

```json
{
  "search_defaults": {
    "top_k": 10,
    "rrf_k": 60,
    "vector_weight": 0.7,
    "fts_weight": 0.3
  }
}
```

## Optional Cross-Encoder Rescoring

RRF scores are good for ranking but poor for thresholding. The scores cluster in a narrow range (typically 0.001–0.016) because the `1/(k + rank)` formula compresses differences. A score of 0.016 might be highly relevant while 0.012 is noise — but there's no principled way to set a cutoff.

When a reranker endpoint is configured, ragling sends the top candidates to a cross-encoder model that produces calibrated relevance scores between 0.0 and 1.0. These replace the RRF scores, enabling consumers to filter by score quality (e.g., `min_score=0.3` to drop low-confidence results).

### How it works

1. **Oversample.** `perform_search` requests `3 × top_k` results from the RRF merge instead of `top_k`, giving the cross-encoder more candidates to evaluate.
2. **Rescore.** The top `3 × top_k` candidates are sent to the Infinity `/rerank` endpoint along with the original query. The cross-encoder evaluates each (query, document) pair and returns a relevance score.
3. **Replace and filter.** RRF scores are replaced with cross-encoder scores. Results are re-sorted by the new scores and filtered by `min_score`.
4. **Truncate.** The final list is truncated to the originally requested `top_k`.

### Worked example (continuing from above)

Starting with the RRF results: C (0.0160), A (0.0115), B (0.0113), D (0.0048), E (0.0048).

The cross-encoder evaluates each document against "kubernetes deployment strategy":

| Document | RRF Score | Cross-Encoder Score | Interpretation |
|----------|-----------|---------------------|----------------|
| Doc C    | 0.0160    | 0.92                | Highly relevant — direct match |
| Doc A    | 0.0115    | 0.78                | Relevant — covers the topic |
| Doc D    | 0.0048    | 0.65                | Moderately relevant |
| Doc B    | 0.0113    | 0.31                | Tangentially related |
| Doc E    | 0.0048    | 0.08                | Not relevant |

**New ranking:** C (0.92), A (0.78), D (0.65), B (0.31), E (0.08)

With `min_score=0.3`: C, A, D, B are returned. Doc E is filtered out.

Notice that Doc D jumped from 4th to 3rd — the cross-encoder recognized it as more relevant than Doc B despite RRF ranking them differently. And the scores now have clear semantic meaning: 0.92 is confidently relevant, 0.08 is confidently irrelevant.

### Graceful degradation

If the reranker endpoint is unavailable (down, timed out, returns an error), the original RRF scores are preserved unchanged. The response includes a `"reranked": false` flag so consumers know whether scores are calibrated cross-encoder scores or compressed RRF scores.

## Implementation Reference

The search pipeline lives in `src/ragling/search/search.py`:

- `_vector_search()` — runs the sqlite-vec nearest-neighbor query
- `_fts_search()` — runs the FTS5 keyword query
- `rrf_merge()` — combines both ranked lists using the formula above
- `search()` — orchestrates the full pipeline: run both searches, merge, apply filters, fetch full document data
- `rescore()` (in `src/ragling/search/rescore.py`) — sends candidates to an Infinity cross-encoder, replaces RRF scores with calibrated relevance scores

All filtering (by collection, source type, date range, sender) happens after RRF merge but before rescoring. Rescoring runs after filtering, before the final `top_k` truncation.
