"""NetNewsWire RSS indexer.

Indexes RSS articles from NetNewsWire's SQLite databases into the "rss"
system collection. Discovers account directories automatically and opens
all databases in read-only mode with retry logic for handling lock contention.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ragling.indexing_status import IndexingStatus

from ragling.config import Config
from ragling.docling_bridge import rss_to_docling_doc
from ragling.docling_convert import chunk_with_hybrid
from ragling.db import get_or_create_collection
from ragling.embeddings import get_embeddings
from ragling.indexers.base import BaseIndexer, IndexResult, upsert_source_with_chunks
from ragling.parsers.rss import Article, find_account_dirs, parse_articles

logger = logging.getLogger(__name__)

MAX_LOCK_RETRIES = 3
LOCK_RETRY_DELAY = 2.0  # seconds


class RSSIndexer(BaseIndexer):
    """Indexes RSS articles from NetNewsWire into the RAG database."""

    def __init__(self, db_path: str | None = None):
        """Initialize the RSS indexer.

        Args:
            db_path: Optional explicit path to the NetNewsWire Accounts
                directory or a specific account directory. If not provided,
                will be determined from config.
        """
        self._explicit_db_path = db_path

    def index(
        self,
        conn: sqlite3.Connection,
        config: Config,
        force: bool = False,
        *,
        status: IndexingStatus | None = None,
    ) -> IndexResult:
        """Index RSS articles from NetNewsWire into the "rss" collection.

        Discovers all account directories and indexes articles from each.

        Args:
            conn: SQLite connection to the RAG database.
            config: Application configuration.
            force: If True, re-index all articles regardless of prior indexing.
            status: Optional indexing status tracker for file-level progress.

        Returns:
            IndexResult summarizing what was done.
        """
        result = IndexResult()

        # Locate NetNewsWire account directories
        if self._explicit_db_path:
            explicit_path = Path(self._explicit_db_path).expanduser()
            if (explicit_path / "DB.sqlite3").is_file():
                account_dirs = [explicit_path]
            else:
                account_dirs = find_account_dirs(explicit_path)

            if not account_dirs:
                msg = f"No NetNewsWire databases found at {explicit_path}"
                logger.error(msg)
                result.errors = 1
                result.error_messages.append(msg)
                return result
        else:
            account_dirs = find_account_dirs(config.netnewswire_db_path)
            if not account_dirs:
                msg = (
                    f"Cannot find NetNewsWire account directories. "
                    f"Checked: {config.netnewswire_db_path}. "
                    "Set netnewswire_db_path in config or pass the path explicitly."
                )
                logger.error(msg)
                result.errors = 1
                result.error_messages.append(msg)
                return result

        logger.info("Found %d NetNewsWire account(s)", len(account_dirs))

        # Get/create the rss system collection
        collection_id = get_or_create_collection(
            conn, "rss", "system", "RSS articles from NetNewsWire"
        )

        # Determine watermark for incremental indexing
        since_ts = None
        if not force:
            since_ts = self._get_watermark(conn, collection_id)
            if since_ts:
                logger.info("Incremental index: fetching articles since ts=%s", since_ts)

        latest_ts = since_ts or 0.0

        # Index each account
        for account_dir in account_dirs:
            logger.info("Indexing account: %s", account_dir.name)
            account_result, account_latest = self._index_account(
                conn, config, collection_id, account_dir, since_ts, force, status=status
            )

            result.total_found += account_result.total_found
            result.indexed += account_result.indexed
            result.skipped += account_result.skipped
            result.errors += account_result.errors
            result.error_messages.extend(account_result.error_messages)

            if account_latest > latest_ts:
                latest_ts = account_latest

        # Update watermark
        if latest_ts > 0:
            self._set_watermark(conn, collection_id, latest_ts)

        logger.info("RSS indexing complete: %s", result)
        return result

    def _index_account(
        self,
        conn: sqlite3.Connection,
        config: Config,
        collection_id: int,
        account_dir: Path,
        since_ts: float | None,
        force: bool,
        *,
        status: IndexingStatus | None = None,
    ) -> tuple[IndexResult, float]:
        """Index articles from a single account directory.

        Returns:
            Tuple of (IndexResult, latest_timestamp).
        """
        result = IndexResult()
        latest_ts = 0.0

        articles = self._parse_with_retry(account_dir, since_ts)
        if articles is None:
            msg = f"Failed to open NetNewsWire database in {account_dir.name} after retries"
            logger.error(msg)
            result.errors = 1
            result.error_messages.append(msg)
            return result, latest_ts

        total_articles = len(articles)
        result.total_found = total_articles
        logger.info("Found %d articles to process in %s", total_articles, account_dir.name)

        # Scan pass: identify new articles
        new_articles: list[Article] = []
        for article in articles:
            if not force and self._is_indexed(conn, collection_id, article.article_id):
                result.skipped += 1
            else:
                new_articles.append(article)

        # Report file-level totals (bytes=0 for RSS)
        if status and new_articles:
            status.set_file_total("rss", len(new_articles), 0)

        # Index pass: process new articles with per-item status ticks
        for i, article in enumerate(new_articles, 1):
            try:
                chunks_count = self._index_article(conn, config, collection_id, article)
                result.indexed += 1

                logger.info(
                    "Indexed article [%d/%d]: %s (%d chunks)",
                    i,
                    len(new_articles),
                    (article.title or "(no title)")[:60],
                    chunks_count,
                )

                # Track latest timestamp for watermark
                if article.date_published_ts > latest_ts:
                    latest_ts = article.date_published_ts

            except Exception as e:
                result.errors += 1
                msg = f"Error indexing article {article.article_id}: {e}"
                if result.errors <= 10:
                    logger.warning(msg)
                    result.error_messages.append(msg)
                elif result.errors == 11:
                    logger.warning("Suppressing further indexing errors...")
            finally:
                if status:
                    status.file_processed("rss", 1, 0)

            # Periodic progress summary
            if i % 500 == 0:
                logger.info(
                    "Progress: %d/%d processed (%d indexed, %d skipped, %d errors)",
                    i,
                    len(new_articles),
                    result.indexed,
                    result.skipped,
                    result.errors,
                )

        logger.info(
            "Account %s complete: %d found, %d indexed, %d skipped, %d errors",
            account_dir.name,
            result.total_found,
            result.indexed,
            result.skipped,
            result.errors,
        )

        return result, latest_ts

    def _parse_with_retry(self, account_dir: Path, since_ts: float | None) -> list[Article] | None:
        """Try to parse articles with retry on database lock."""
        for attempt in range(1, MAX_LOCK_RETRIES + 1):
            try:
                articles = list(parse_articles(account_dir, since_ts))
                return articles
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() or "busy" in str(e).lower():
                    if attempt < MAX_LOCK_RETRIES:
                        logger.warning(
                            "NetNewsWire database is locked (attempt %d/%d), retrying in %ds...",
                            attempt,
                            MAX_LOCK_RETRIES,
                            LOCK_RETRY_DELAY,
                        )
                        time.sleep(LOCK_RETRY_DELAY)
                    else:
                        logger.error(
                            "NetNewsWire database is locked after %d attempts. "
                            "Try closing NetNewsWire and running again.",
                            MAX_LOCK_RETRIES,
                        )
                        return None
                else:
                    logger.error("Database error: %s", e)
                    return None

        return None

    def _is_indexed(self, conn: sqlite3.Connection, collection_id: int, article_id: str) -> bool:
        """Check if an article is already indexed."""
        row = conn.execute(
            "SELECT id FROM sources WHERE collection_id = ? AND source_path = ?",
            (collection_id, article_id),
        ).fetchone()
        return row is not None

    def _index_article(
        self,
        conn: sqlite3.Connection,
        config: Config,
        collection_id: int,
        article: Article,
    ) -> int:
        """Index a single article: chunk, embed, and insert.

        Returns:
            Number of chunks indexed.
        """
        # Build DoclingDocument via bridge and chunk with HybridChunker
        doc = rss_to_docling_doc(article.title, article.body_text)
        extra_metadata: dict = {
            "url": article.url,
            "feed_name": article.feed_name,
            "date": article.date_published,
        }
        if article.feed_category:
            extra_metadata["feed_category"] = article.feed_category
        if article.authors:
            extra_metadata["authors"] = article.authors

        chunks = chunk_with_hybrid(
            doc,
            title=article.title or "(no title)",
            source_path=article.article_id,
            extra_metadata=extra_metadata,
        )

        if not chunks:
            logger.warning(
                "No chunks produced for article '%s' (article_id=%s)",
                article.title or "(no title)",
                article.article_id,
            )
            return 0

        # Embed all chunks
        chunk_texts = [c.text for c in chunks]
        embeddings = get_embeddings(chunk_texts, config)

        upsert_source_with_chunks(
            conn,
            collection_id=collection_id,
            source_path=article.article_id,
            source_type="rss",
            chunks=chunks,
            embeddings=embeddings,
        )
        return len(chunks)

    def _get_watermark(self, conn: sqlite3.Connection, collection_id: int) -> float | None:
        """Get the latest indexed article timestamp for incremental updates."""
        row = conn.execute(
            """
            SELECT MAX(json_extract(d.metadata, '$.date')) as latest_date
            FROM documents d
            WHERE d.collection_id = ?
            """,
            (collection_id,),
        ).fetchone()

        if row and row["latest_date"]:
            # Convert ISO date back to timestamp for comparison
            try:
                dt = datetime.fromisoformat(row["latest_date"])
                return dt.timestamp()
            except (ValueError, OSError):
                logger.warning(
                    "Failed to parse watermark date '%s', starting full index",
                    row["latest_date"],
                )
                return None
        return None

    def _set_watermark(self, conn: sqlite3.Connection, collection_id: int, ts: float) -> None:
        """Store the watermark timestamp in the collection description."""
        from ragling.parsers.rss import _ts_to_iso

        date_str = _ts_to_iso(ts)
        conn.execute(
            "UPDATE collections SET description = ? WHERE id = ?",
            (f"RSS articles from NetNewsWire (indexed through {date_str})", collection_id),
        )
        conn.commit()
