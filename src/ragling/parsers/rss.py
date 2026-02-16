"""NetNewsWire RSS article parser.

Reads articles from NetNewsWire's per-account SQLite databases in read-only
mode and yields structured Article objects.

NetNewsWire stores data in account directories under:
    ~/Library/Containers/com.ranchero.NetNewsWire-Evergreen/
        Data/Library/Application Support/NetNewsWire/Accounts/

Each account directory contains:
    DB.sqlite3          — articles, authors, statuses tables
    Subscriptions.opml  — feed names and categories

Articles have contentHTML (usually populated) and contentText (usually empty).
datePublished is a Unix timestamp.
"""

import logging
import plistlib
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class Article:
    """A parsed RSS article."""

    article_id: str
    title: str
    body_text: str
    url: str = ""
    feed_name: str = ""
    feed_category: str = ""
    authors: list[str] = field(default_factory=list)
    date_published: str = ""
    date_published_ts: float = 0.0


def _open_ro(db_path: Path) -> sqlite3.Connection | None:
    """Open a SQLite database in read-only mode."""
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        logger.warning("Cannot open %s: %s", db_path, e)
        return None


def _ts_to_iso(ts: int | float | None) -> str:
    """Convert a Unix timestamp to an ISO datetime string."""
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.isoformat()
    except (OverflowError, ValueError, OSError):
        return ""


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text using BeautifulSoup."""
    if not html or not html.strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def find_account_dirs(base_path: Path) -> list[Path]:
    """Find NetNewsWire account directories containing DB.sqlite3.

    Args:
        base_path: The NetNewsWire Accounts directory.

    Returns:
        List of account directories that contain DB.sqlite3.
    """
    account_dirs: list[Path] = []

    if not base_path.is_dir():
        return account_dirs

    for child in sorted(base_path.iterdir()):
        if not child.is_dir():
            continue
        if (child / "DB.sqlite3").is_file():
            account_dirs.append(child)

    return account_dirs


def _load_feed_id_map(account_dir: Path) -> dict[str, tuple[str, str]]:
    """Load feedID → (feed name, category) mapping from FeedMetadata.plist.

    NetNewsWire stores a FeedMetadata.plist per account with entries keyed
    by feed XML URL. Each entry contains the feedID and folderRelationship
    (which maps category labels to feed IDs).

    The feed name is derived from the XML URL's path, and the category
    from the folder relationship labels (e.g. "user/-/label/Tech" → "Tech").

    Falls back to Subscriptions.opml for human-readable feed names.

    Returns:
        Dict mapping feedID (e.g. "feed/7") to (feed name, category).
    """
    plist_path = account_dir / "FeedMetadata.plist"
    if not plist_path.is_file():
        logger.info("FeedMetadata.plist not found in %s", account_dir)
        return {}

    try:
        with open(plist_path, "rb") as f:
            plist_data = plistlib.load(f)
    except Exception as e:
        logger.warning("Cannot read FeedMetadata.plist: %s", e)
        return {}

    # Also load OPML for human-readable feed names
    opml_names = _load_opml_names(account_dir)

    result: dict[str, tuple[str, str]] = {}

    for xml_url, entry in plist_data.items():
        feed_id = entry.get("feedID", "")
        if not feed_id:
            continue

        # Extract category from folderRelationship keys
        # Keys look like "user/-/label/Tech"
        category = ""
        folder_rel = entry.get("folderRelationship", {})
        for label_key in folder_rel:
            if "/label/" in label_key:
                category = label_key.split("/label/", 1)[1]
                break

        # Get human-readable name: prefer OPML, fall back to URL
        feed_name = opml_names.get(xml_url, "")
        if not feed_name:
            # Extract name from URL path
            from urllib.parse import urlparse

            try:
                parsed = urlparse(xml_url)
                feed_name = parsed.netloc or xml_url
            except Exception:
                feed_name = xml_url

        result[feed_id] = (feed_name, category)

    return result


def _load_opml_names(account_dir: Path) -> dict[str, str]:
    """Load xmlUrl → feed title mapping from Subscriptions.opml.

    Returns:
        Dict mapping feed XML URL to its human-readable title.
    """
    import xml.etree.ElementTree as ET

    opml_path = account_dir / "Subscriptions.opml"
    if not opml_path.is_file():
        return {}

    try:
        tree = ET.parse(opml_path)
    except ET.ParseError as e:
        logger.warning("Cannot parse %s: %s", opml_path, e)
        return {}

    names: dict[str, str] = {}
    body = tree.find("body")
    if body is None:
        return names

    for outline in body:
        xml_url = outline.get("xmlUrl")
        if xml_url:
            names[xml_url] = outline.get("text", outline.get("title", ""))
        else:
            for feed_outline in outline:
                feed_url = feed_outline.get("xmlUrl")
                if feed_url:
                    names[feed_url] = feed_outline.get("text", feed_outline.get("title", ""))

    return names


def _load_authors(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Load article ID → author names mapping.

    Returns:
        Dict mapping articleID to list of author name strings.
    """
    try:
        rows = conn.execute(
            "SELECT al.articleID, a.name "
            "FROM authorsLookup al "
            "JOIN authors a ON al.authorID = a.authorID "
            "WHERE a.name IS NOT NULL AND a.name != ''"
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("Cannot read authors: %s", e)
        return {}

    authors: dict[str, list[str]] = {}
    for row in rows:
        aid = row["articleID"]
        if aid not in authors:
            authors[aid] = []
        authors[aid].append(row["name"])

    return authors


def parse_articles(account_dir: str | Path, since_ts: float | None = None) -> Iterator[Article]:
    """Parse articles from a NetNewsWire account directory.

    Opens the database in read-only mode.

    Args:
        account_dir: Path to the account directory containing DB.sqlite3.
        since_ts: Only return articles published after this Unix timestamp.
            If None, returns all articles.

    Yields:
        Article objects for each parsed article.
    """
    account_dir = Path(account_dir)
    db_path = account_dir / "DB.sqlite3"

    if not db_path.is_file():
        logger.error("DB.sqlite3 not found in %s", account_dir)
        return

    conn = _open_ro(db_path)
    if not conn:
        return

    try:
        # Load supporting data
        feed_id_map = _load_feed_id_map(account_dir)
        authors_map = _load_authors(conn)

        logger.info(
            "Loaded %d feed mappings, %d author sets",
            len(feed_id_map),
            len(authors_map),
        )

        # Build query
        query = (
            "SELECT articleID, feedID, title, contentHTML, contentText, "
            "url, externalURL, summary, datePublished "
            "FROM articles"
        )
        params: list = []

        if since_ts:
            query += " WHERE datePublished > ?"
            params.append(since_ts)

        query += " ORDER BY datePublished ASC"

        cursor = conn.execute(query, params)
        row_count = 0
        error_count = 0

        for row in cursor:
            try:
                article = _row_to_article(row, feed_id_map, authors_map)
                if article:
                    row_count += 1
                    yield article
            except Exception as e:
                error_count += 1
                if error_count <= 10:
                    logger.warning("Error parsing article %s: %s", row["articleID"], e)
                elif error_count == 11:
                    logger.warning("Suppressing further article parse errors...")

        logger.info("Parsed %d articles (%d errors)", row_count, error_count)

    except sqlite3.OperationalError as e:
        logger.error("Error reading DB.sqlite3: %s", e)
    finally:
        conn.close()


def _row_to_article(
    row: sqlite3.Row,
    feed_id_map: dict[str, tuple[str, str]],
    authors_map: dict[str, list[str]],
) -> Article | None:
    """Convert an articles table row to an Article."""
    article_id = row["articleID"]
    title = row["title"] or ""
    url = row["url"] or row["externalURL"] or ""
    date_published_ts = row["datePublished"] or 0

    # Extract body text: prefer contentText, fall back to contentHTML, then summary
    body = row["contentText"] or ""
    if not body.strip():
        html = row["contentHTML"] or ""
        if html.strip():
            body = _html_to_text(html)

    if not body.strip():
        summary = row["summary"] or ""
        if summary.strip():
            body = _html_to_text(summary) if "<" in summary else summary

    # Skip articles with no content at all
    if not body.strip() and not title:
        return None

    # Feed info
    feed_name, feed_category = feed_id_map.get(row["feedID"], (row["feedID"], ""))

    # Authors
    authors = authors_map.get(article_id, [])

    return Article(
        article_id=article_id,
        title=title,
        body_text=body.strip(),
        url=url,
        feed_name=feed_name,
        feed_category=feed_category,
        authors=authors,
        date_published=_ts_to_iso(date_published_ts),
        date_published_ts=float(date_published_ts) if date_published_ts else 0.0,
    )
