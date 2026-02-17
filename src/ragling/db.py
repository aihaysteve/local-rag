"""Database initialization, connection management, and migrations for ragling."""

import logging
import sqlite3

import sqlite_vec  # type: ignore[import-untyped]

from ragling.config import Config

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2


def get_connection(config: Config) -> sqlite3.Connection:
    """Open a SQLite connection with sqlite-vec loaded and pragmas set.

    Uses config.group_index_db_path when group is not "default",
    otherwise falls back to config.db_path for backwards compatibility.

    Args:
        config: Application configuration.

    Returns:
        Configured sqlite3.Connection.
    """
    if config.group_name != "default":
        db_path = config.group_index_db_path
    else:
        db_path = config.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row

    return conn


def init_db(conn: sqlite3.Connection, config: Config) -> None:
    """Create all tables, virtual tables, and triggers if they don't exist.

    Args:
        conn: SQLite connection.
        config: Application configuration (used for embedding dimensions).
    """
    dim = config.embedding_dimensions

    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            collection_type TEXT NOT NULL DEFAULT 'project',
            description TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            source_path TEXT NOT NULL,
            file_hash TEXT,
            file_modified_at TEXT,
            last_indexed_at TEXT,
            UNIQUE(collection_id, source_path)
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(source_id, chunk_index)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS vec_documents USING vec0(
            embedding float[{dim}],
            document_id INTEGER
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            title,
            content,
            content='documents',
            content_rowid='id'
        );

        -- Triggers to keep FTS in sync with documents table
        CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, title, content)
            VALUES (new.id, new.title, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, title, content)
            VALUES('delete', old.id, old.title, old.content);
        END;

        CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, title, content)
            VALUES('delete', old.id, old.title, old.content);
            INSERT INTO documents_fts(rowid, title, content)
            VALUES (new.id, new.title, new.content);
        END;

        -- Schema version tracking
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """
    )

    # Set schema version if not already set
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    conn.commit()

    # Run any pending migrations
    migrate(conn, config)

    logger.info(
        "Database initialized (schema version %d, embedding dim %d)",
        SCHEMA_VERSION,
        dim,
    )


def migrate(conn: sqlite3.Connection, config: Config) -> None:
    """Run any pending schema migrations.

    Args:
        conn: SQLite connection.
        config: Application configuration.
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        # Fresh database, init will handle it
        init_db(conn, config)
        return

    current_version = int(row["value"])

    if current_version >= SCHEMA_VERSION:
        logger.debug("Database schema is up to date (version %d)", current_version)
        return

    if current_version < 2:
        # Reclassify git repo collections from 'project' to 'code'.
        # Git repos are identified by their watermark description (starts with "git-").
        conn.execute(
            "UPDATE collections SET collection_type = 'code' "
            "WHERE collection_type = 'project' AND description LIKE 'git-%'"
        )
        conn.commit()
        logger.info("Migration v2: reclassified git repo collections as 'code'")

    conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'schema_version'",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    logger.info("Database migrated to schema version %d", SCHEMA_VERSION)


def get_or_create_collection(
    conn: sqlite3.Connection,
    name: str,
    collection_type: str = "project",
    description: str | None = None,
) -> int:
    """Get or create a collection by name.

    Args:
        conn: SQLite connection.
        name: Collection name.
        collection_type: 'system', 'project', or 'code'.
        description: Optional description.

    Returns:
        The collection ID.
    """
    row = conn.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]

    cursor = conn.execute(
        "INSERT INTO collections (name, collection_type, description) VALUES (?, ?, ?)",
        (name, collection_type, description),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    logger.info("Created collection '%s' (type=%s, id=%d)", name, collection_type, cursor.lastrowid)
    return cursor.lastrowid


def delete_collection(conn: sqlite3.Connection, name: str) -> bool:
    """Delete a collection and all its data (sources, documents, vectors).

    Args:
        conn: SQLite connection.
        name: Collection name to delete.

    Returns:
        True if the collection existed and was deleted, False if not found.
    """
    row = conn.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
    if not row:
        return False

    coll_id = row["id"]

    # Delete vector embeddings (not covered by CASCADE since vec_documents
    # is a virtual table without foreign key support)
    conn.execute(
        "DELETE FROM vec_documents WHERE document_id IN "
        "(SELECT id FROM documents WHERE collection_id = ?)",
        (coll_id,),
    )

    # CASCADE handles sources and documents
    conn.execute("DELETE FROM collections WHERE id = ?", (coll_id,))
    conn.commit()

    logger.info("Deleted collection '%s' (id=%d)", name, coll_id)
    return True
