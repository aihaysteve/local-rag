"""Cross-encoder rescoring of search results via Infinity reranking API."""

from __future__ import annotations

import logging
from dataclasses import replace

import httpx

from ragling.config import RerankerConfig
from ragling.search.search import SearchResult

logger = logging.getLogger(__name__)

_client: httpx.Client | None = None
_client_verify: bool | None = None


def _get_client(*, verify: bool = True) -> httpx.Client:
    """Return a reusable HTTP client for connection pooling.

    Recreates the client if the ``verify`` setting changes.
    """
    global _client, _client_verify  # noqa: PLW0603
    if _client is None or _client_verify != verify:
        if _client is not None:
            _client.close()
        _client = httpx.Client(timeout=10.0, verify=verify)
        _client_verify = verify
    return _client


def rescore(
    query: str,
    results: list[SearchResult],
    config: RerankerConfig,
    min_score: float | None = None,
) -> tuple[list[SearchResult], bool]:
    """Rescore search results using a cross-encoder reranking model.

    Sends results to the Infinity ``/rerank`` endpoint, replaces each
    result's RRF score with the reranker's ``relevance_score``, re-sorts
    descending, and filters by ``min_score``.

    On any failure (connection error, timeout, malformed response), returns
    the original results unchanged with ``reranked=False``.

    Args:
        query: The original search query text.
        results: Search results from RRF merge (will not be mutated).
        config: Reranker configuration with endpoint and model.
        min_score: Override for config.min_score. None means use config default.

    Returns:
        Tuple of (results, reranked_flag). ``reranked_flag`` is True only
        when rescoring succeeded and scores were replaced.
    """
    if not results:
        return [], False

    threshold = min_score if min_score is not None else config.min_score

    try:
        response = _get_client(verify=config.verify_tls).post(
            f"{config.endpoint}/rerank",
            json={
                "model": config.model,
                "query": query,
                "documents": [r.content for r in results],
                "return_documents": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        scored = data["results"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Reranker unavailable, falling back to RRF scores: %s", exc)
        return results, False
    except Exception as exc:
        logger.warning("Unexpected reranker error, falling back to RRF scores: %s", exc)
        return results, False

    try:
        rescored = [
            replace(results[item["index"]], score=item["relevance_score"]) for item in scored
        ]
    except (KeyError, IndexError) as exc:
        logger.warning("Malformed reranker response, falling back to RRF scores: %s", exc)
        return results, False

    rescored.sort(key=lambda r: r.score, reverse=True)
    if threshold > 0:
        rescored = [r for r in rescored if r.score >= threshold]

    return rescored, True
