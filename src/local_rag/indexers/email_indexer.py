"""Email indexer for eM Client.

Indexes emails from the eM Client SQLite database into the "email" system
collection. Opens the eM Client database in read-only mode with retry logic
for handling lock contention.
"""

import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from local_rag.chunker import chunk_email
from local_rag.config import Config
from local_rag.db import get_or_create_collection
from local_rag.embeddings import get_embeddings, serialize_float32
from local_rag.indexers.base import BaseIndexer, IndexResult
from local_rag.parsers.email import EmailMessage, parse_emails

logger = logging.getLogger(__name__)

MAX_LOCK_RETRIES = 3
LOCK_RETRY_DELAY = 2.0  # seconds


def _find_emclient_db(config: Config) -> Path | None:
    """Locate the eM Client mail_data.dat file.

    Args:
        config: Application configuration.

    Returns:
        Path to mail_data.dat, or None if not found.
    """
    base = config.emclient_db_path

    # Direct file path
    if base.is_file():
        return base

    # Directory containing mail_data.dat
    candidate = base / "mail_data.dat"
    if candidate.is_file():
        return candidate

    # Search subdirectories (eM Client may use account-specific subdirs)
    if base.is_dir():
        for dat in base.rglob("mail_data.dat"):
            return dat

    return None


class EmailIndexer(BaseIndexer):
    """Indexes emails from eM Client into the RAG database."""

    def __init__(self, db_path: str | None = None):
        """Initialize the email indexer.

        Args:
            db_path: Optional explicit path to the eM Client database.
                If not provided, will be determined from config.
        """
        self._explicit_db_path = db_path

    def index(
        self, conn: sqlite3.Connection, config: Config, force: bool = False
    ) -> IndexResult:
        """Index emails from eM Client into the "email" collection.

        Args:
            conn: SQLite connection to the RAG database.
            config: Application configuration.
            force: If True, re-index all emails regardless of prior indexing.

        Returns:
            IndexResult summarizing what was done.
        """
        result = IndexResult()

        # Locate eM Client database
        if self._explicit_db_path:
            emclient_path = Path(self._explicit_db_path).expanduser()
            if not emclient_path.is_file():
                msg = f"eM Client database not found at {emclient_path}"
                logger.error(msg)
                result.errors = 1
                result.error_messages.append(msg)
                return result
        else:
            emclient_path = _find_emclient_db(config)
            if not emclient_path:
                msg = (
                    f"Cannot find eM Client database. Checked: {config.emclient_db_path}. "
                    "Set emclient_db_path in config or pass the path explicitly."
                )
                logger.error(msg)
                result.errors = 1
                result.error_messages.append(msg)
                return result

        logger.info("Using eM Client database: %s", emclient_path)

        # Get/create the email system collection
        collection_id = get_or_create_collection(
            conn, "email", "system", "Emails from eM Client"
        )

        # Determine watermark for incremental indexing
        since_date = None
        if not force:
            since_date = self._get_watermark(conn, collection_id)
            if since_date:
                logger.info("Incremental index: fetching emails since %s", since_date)

        # Parse emails with retry on lock
        emails = self._parse_with_retry(str(emclient_path), since_date)
        if emails is None:
            msg = "Failed to open eM Client database after retries"
            logger.error(msg)
            result.errors = 1
            result.error_messages.append(msg)
            return result

        latest_date = since_date or ""

        for email_msg in emails:
            result.total_found += 1

            # Skip if already indexed (unless force)
            if not force and self._is_indexed(conn, collection_id, email_msg.message_id):
                result.skipped += 1
                continue

            try:
                self._index_email(conn, config, collection_id, email_msg)
                result.indexed += 1

                # Track latest date for watermark
                if email_msg.date and email_msg.date > latest_date:
                    latest_date = email_msg.date

            except Exception as e:
                result.errors += 1
                msg = f"Error indexing email {email_msg.message_id}: {e}"
                if result.errors <= 10:
                    logger.warning(msg)
                    result.error_messages.append(msg)
                elif result.errors == 11:
                    logger.warning("Suppressing further indexing errors...")

        # Update watermark
        if latest_date:
            self._set_watermark(conn, collection_id, latest_date)

        logger.info("Email indexing complete: %s", result)
        return result

    def _parse_with_retry(
        self, db_path: str, since_date: str | None
    ) -> list[EmailMessage] | None:
        """Try to parse emails with retry on database lock.

        Returns a list of emails, or None if all retries failed.
        """
        for attempt in range(1, MAX_LOCK_RETRIES + 1):
            try:
                # Materialize the iterator to detect lock errors early
                emails = list(parse_emails(db_path, since_date))
                return emails
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() or "busy" in str(e).lower():
                    if attempt < MAX_LOCK_RETRIES:
                        logger.warning(
                            "eM Client database is locked (attempt %d/%d), "
                            "retrying in %ds...",
                            attempt,
                            MAX_LOCK_RETRIES,
                            LOCK_RETRY_DELAY,
                        )
                        time.sleep(LOCK_RETRY_DELAY)
                    else:
                        logger.error(
                            "eM Client database is locked after %d attempts. "
                            "Try closing eM Client and running again.",
                            MAX_LOCK_RETRIES,
                        )
                        return None
                else:
                    logger.error("Database error: %s", e)
                    return None

        return None

    def _is_indexed(
        self, conn: sqlite3.Connection, collection_id: int, message_id: str
    ) -> bool:
        """Check if an email with this message_id is already indexed."""
        row = conn.execute(
            "SELECT id FROM sources WHERE collection_id = ? AND source_path = ?",
            (collection_id, message_id),
        ).fetchone()
        return row is not None

    def _index_email(
        self,
        conn: sqlite3.Connection,
        config: Config,
        collection_id: int,
        email_msg: EmailMessage,
    ) -> None:
        """Index a single email: chunk, embed, and insert."""
        # Chunk the email
        chunks = chunk_email(
            subject=email_msg.subject,
            body=email_msg.body_text,
            chunk_size=config.chunk_size_tokens,
            overlap=config.chunk_overlap_tokens,
        )

        if not chunks:
            return

        # Embed all chunks
        chunk_texts = [c.text for c in chunks]
        embeddings = get_embeddings(chunk_texts, config)

        # Build metadata
        metadata = {
            "sender": email_msg.sender,
            "recipients": email_msg.recipients,
            "date": email_msg.date,
            "folder": email_msg.folder,
        }
        metadata_json = json.dumps(metadata)

        now = datetime.now().isoformat()

        # Delete existing source if re-indexing (force mode)
        conn.execute(
            "DELETE FROM sources WHERE collection_id = ? AND source_path = ?",
            (collection_id, email_msg.message_id),
        )

        # Insert source
        cursor = conn.execute(
            """
            INSERT INTO sources (collection_id, source_type, source_path, last_indexed_at)
            VALUES (?, 'email', ?, ?)
            """,
            (collection_id, email_msg.message_id, now),
        )
        source_id = cursor.lastrowid

        # Insert documents and vectors
        for chunk, embedding in zip(chunks, embeddings):
            doc_cursor = conn.execute(
                """
                INSERT INTO documents (source_id, collection_id, chunk_index,
                                       title, content, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    collection_id,
                    chunk.chunk_index,
                    email_msg.subject or "(no subject)",
                    chunk.text,
                    metadata_json,
                ),
            )
            doc_id = doc_cursor.lastrowid

            conn.execute(
                "INSERT INTO vec_documents (rowid, embedding, document_id) VALUES (?, ?, ?)",
                (doc_id, serialize_float32(embedding), doc_id),
            )

        conn.commit()

    def _get_watermark(
        self, conn: sqlite3.Connection, collection_id: int
    ) -> str | None:
        """Get the latest indexed email date for incremental updates."""
        row = conn.execute(
            """
            SELECT MAX(json_extract(d.metadata, '$.date')) as latest_date
            FROM documents d
            WHERE d.collection_id = ?
            """,
            (collection_id,),
        ).fetchone()

        if row and row["latest_date"]:
            return row["latest_date"]
        return None

    def _set_watermark(
        self, conn: sqlite3.Connection, collection_id: int, date: str
    ) -> None:
        """Store the watermark date in the collection description for tracking."""
        conn.execute(
            "UPDATE collections SET description = ? WHERE id = ?",
            (f"Emails from eM Client (indexed through {date})", collection_id),
        )
        conn.commit()
