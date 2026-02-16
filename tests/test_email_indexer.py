"""Tests for ragling.indexers.email_indexer -- HybridChunker integration."""

from unittest.mock import MagicMock, patch

from ragling.chunker import Chunk
from ragling.config import Config


class TestEmailIndexerChunking:
    """Tests that email indexer uses HybridChunker via bridge function."""

    def test_index_email_uses_chunk_with_hybrid(self) -> None:
        """_index_email should call chunk_with_hybrid, not chunk_email."""
        from ragling.indexers.email_indexer import EmailIndexer

        indexer = EmailIndexer()
        email_msg = MagicMock()
        email_msg.subject = "Test subject"
        email_msg.body_text = "Email body text here."
        email_msg.message_id = "msg-123"
        email_msg.sender = "alice@example.com"
        email_msg.recipients = "bob@example.com"
        email_msg.date = "2025-01-01T00:00:00"
        email_msg.folder = "Inbox"

        config = Config(chunk_size_tokens=256)

        mock_conn = MagicMock()
        mock_conn.execute.return_value.lastrowid = 1

        with (
            patch("ragling.indexers.email_indexer.chunk_with_hybrid") as mock_hybrid,
            patch("ragling.indexers.email_indexer.get_embeddings") as mock_embed,
        ):
            mock_hybrid.return_value = [
                Chunk(
                    text="contextualized text",
                    title="Test subject",
                    chunk_index=0,
                    metadata={
                        "source_path": "msg-123",
                        "sender": "alice@example.com",
                    },
                )
            ]
            mock_embed.return_value = [[0.1] * 1024]
            indexer._index_email(mock_conn, config, 1, email_msg)

        mock_hybrid.assert_called_once()

    def test_index_email_passes_domain_metadata(self) -> None:
        """chunk_with_hybrid receives sender, recipients, date, folder as extra_metadata."""
        from ragling.indexers.email_indexer import EmailIndexer

        indexer = EmailIndexer()
        email_msg = MagicMock()
        email_msg.subject = "Meeting"
        email_msg.body_text = "Let's meet."
        email_msg.message_id = "msg-456"
        email_msg.sender = "alice@example.com"
        email_msg.recipients = "bob@example.com"
        email_msg.date = "2025-01-01T00:00:00"
        email_msg.folder = "Sent"

        config = Config(chunk_size_tokens=256)
        mock_conn = MagicMock()
        mock_conn.execute.return_value.lastrowid = 1

        with (
            patch("ragling.indexers.email_indexer.chunk_with_hybrid") as mock_hybrid,
            patch("ragling.indexers.email_indexer.get_embeddings") as mock_embed,
        ):
            mock_hybrid.return_value = [
                Chunk(text="text", title="Meeting", chunk_index=0, metadata={})
            ]
            mock_embed.return_value = [[0.1] * 1024]
            indexer._index_email(mock_conn, config, 1, email_msg)

        call_kwargs = mock_hybrid.call_args.kwargs
        extra = call_kwargs.get("extra_metadata", {})
        assert extra["sender"] == "alice@example.com"
        assert extra["recipients"] == "bob@example.com"
        assert extra["date"] == "2025-01-01T00:00:00"
        assert extra["folder"] == "Sent"

    def test_no_chunk_email_import(self) -> None:
        """Email indexer should not import chunk_email anymore."""
        import ragling.indexers.email_indexer as mod

        assert not hasattr(mod, "chunk_email"), "chunk_email should not be imported"
