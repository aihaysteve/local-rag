"""Tests for ragling.indexers.rss_indexer -- HybridChunker integration."""

from unittest.mock import MagicMock, patch

from ragling.chunker import Chunk
from ragling.config import Config


class TestRSSIndexerChunking:
    """Tests that RSS indexer uses HybridChunker via bridge function."""

    def test_index_article_uses_chunk_with_hybrid(self) -> None:
        """_index_article should call chunk_with_hybrid, not chunk_email."""
        from ragling.indexers.rss_indexer import RSSIndexer

        indexer = RSSIndexer()
        article = MagicMock()
        article.title = "Test Article"
        article.body_text = "Article body text here."
        article.article_id = "article-123"
        article.url = "https://example.com/article"
        article.feed_name = "Test Feed"
        article.date_published = "2025-01-01T00:00:00"
        article.feed_category = "Tech"
        article.authors = "Alice"

        config = Config(chunk_size_tokens=256)

        mock_conn = MagicMock()
        mock_conn.execute.return_value.lastrowid = 1

        with (
            patch("ragling.indexers.rss_indexer.chunk_with_hybrid") as mock_hybrid,
            patch("ragling.indexers.rss_indexer.get_embeddings") as mock_embed,
        ):
            mock_hybrid.return_value = [
                Chunk(
                    text="contextualized text",
                    title="Test Article",
                    chunk_index=0,
                    metadata={"source_path": "article-123"},
                )
            ]
            mock_embed.return_value = [[0.1] * 1024]
            indexer._index_article(mock_conn, config, 1, article)

        mock_hybrid.assert_called_once()

    def test_index_article_passes_domain_metadata(self) -> None:
        """chunk_with_hybrid receives url, feed_name, date, etc. as extra_metadata."""
        from ragling.indexers.rss_indexer import RSSIndexer

        indexer = RSSIndexer()
        article = MagicMock()
        article.title = "News Article"
        article.body_text = "Some news."
        article.article_id = "art-456"
        article.url = "https://example.com/news"
        article.feed_name = "News Feed"
        article.date_published = "2025-06-01T12:00:00"
        article.feed_category = "Politics"
        article.authors = "Bob"

        config = Config(chunk_size_tokens=256)
        mock_conn = MagicMock()
        mock_conn.execute.return_value.lastrowid = 1

        with (
            patch("ragling.indexers.rss_indexer.chunk_with_hybrid") as mock_hybrid,
            patch("ragling.indexers.rss_indexer.get_embeddings") as mock_embed,
        ):
            mock_hybrid.return_value = [
                Chunk(text="text", title="News Article", chunk_index=0, metadata={})
            ]
            mock_embed.return_value = [[0.1] * 1024]
            indexer._index_article(mock_conn, config, 1, article)

        call_kwargs = mock_hybrid.call_args.kwargs
        extra = call_kwargs.get("extra_metadata", {})
        assert extra["url"] == "https://example.com/news"
        assert extra["feed_name"] == "News Feed"
        assert extra["date"] == "2025-06-01T12:00:00"
        assert extra["feed_category"] == "Politics"
        assert extra["authors"] == "Bob"

    def test_no_chunk_email_import(self) -> None:
        """RSS indexer should not import chunk_email anymore."""
        import ragling.indexers.rss_indexer as mod

        assert not hasattr(mod, "chunk_email"), "chunk_email should not be imported"
