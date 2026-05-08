"""Tests for the retrieval system."""

import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock

from retrieval import TextChunker, EmbeddingService, RetrievalService, DocumentIngestionService
from db.models import DocumentSource


class TestTextChunker:
    """Test the text chunking functionality."""

    def test_chunk_text_basic(self):
        """Test basic text chunking."""
        chunker = TextChunker(chunk_size=100, overlap=20)
        text = "This is a test document. " * 50  # Repeat to create longer text

        chunks = chunker.chunk_text(text)

        assert len(chunks) > 1
        assert all(chunk["token_count"] <= 100 for chunk in chunks)
        assert all(chunk["content"].strip() for chunk in chunks)

    def test_chunk_text_overlap(self):
        """Test that chunks have proper overlap."""
        chunker = TextChunker(chunk_size=50, overlap=10)
        text = "word " * 100

        chunks = chunker.chunk_text(text)

        # Check that consecutive chunks share some content
        if len(chunks) > 1:
            first_end = chunks[0]["content"].split()[-10:]  # Last 10 words of first chunk
            second_start = chunks[1]["content"].split()[:10]  # First 10 words of second chunk
            # There should be some overlap
            overlap = set(first_end) & set(second_start)
            assert len(overlap) > 0


class TestEmbeddingService:
    """Test the embedding service."""

    def test_encode_single_text(self):
        """Test encoding a single text."""
        service = EmbeddingService()

        text = "This is a test sentence."
        embedding = service.encode_single(text)

        assert isinstance(embedding, list)
        assert len(embedding) == service.dimension
        assert all(isinstance(x, float) for x in embedding)

    def test_encode_multiple_texts(self):
        """Test encoding multiple texts."""
        service = EmbeddingService()

        texts = ["First sentence.", "Second sentence."]
        embeddings = service.encode(texts)

        assert embeddings.shape == (2, service.dimension)

    def test_similarity_calculation(self):
        """Test cosine similarity calculation."""
        service = EmbeddingService()

        # Create two identical vectors
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [1.0, 0.0, 0.0]

        similarity = service.similarity(vec1, vec2)
        assert similarity == pytest.approx(1.0)

        # Create orthogonal vectors
        vec3 = [1.0, 0.0, 0.0]
        vec4 = [0.0, 1.0, 0.0]

        similarity = service.similarity(vec3, vec4)
        assert similarity == pytest.approx(0.0)


class TestRetrievalService:
    """Test the retrieval service."""

    @pytest.fixture
    def mock_embedding_service(self):
        """Create a mock embedding service."""
        service = MagicMock(spec=EmbeddingService)
        service.encode_single.return_value = [0.1, 0.2, 0.3, 0.4] * 96  # 384 dimensions
        service.similarity.return_value = 0.8
        return service

    @pytest.fixture
    def retrieval_service(self, mock_embedding_service):
        """Create a retrieval service with mock embedding service."""
        return RetrievalService(mock_embedding_service)

    @pytest.mark.asyncio
    async def test_retrieve_no_chunks(self, retrieval_service):
        """Test retrieval when no chunks exist."""
        mock_db_session = AsyncMock()
        mock_db_session.execute.return_value.scalars.return_value.all.return_value = []

        results = await retrieval_service.retrieve(
            query="test query",
            db_session=mock_db_session
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_with_chunks(self, retrieval_service, mock_embedding_service):
        """Test retrieval with existing chunks."""
        # Mock chunks
        mock_chunk = MagicMock()
        mock_chunk.id = "chunk1"
        mock_chunk.content = "Test content"
        mock_chunk.document_id = "doc1"
        mock_chunk.chunk_index = 0
        mock_chunk.embedding = [0.1] * 384
        mock_chunk.metadata = {}

        mock_db_session = AsyncMock()
        mock_db_session.execute.return_value.scalars.return_value.all.return_value = [mock_chunk]

        # Mock the semantic search query result
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("chunk1", "doc1", 0, "Test content", {}, 0.9)]
        mock_db_session.execute.return_value = mock_result

        results = await retrieval_service.retrieve(
            query="test query",
            db_session=mock_db_session
        )

        assert len(results) == 1
        assert results[0].chunk_id == "chunk1"
        assert results[0].content == "Test content"


class TestDocumentIngestionService:
    """Test the document ingestion service."""

    @pytest.fixture
    def mock_chunker(self):
        """Create a mock chunker."""
        chunker = MagicMock(spec=TextChunker)
        chunker.chunk_text.return_value = [
            {"content": "Chunk 1", "token_count": 10, "chunk_index": 0, "metadata": {}},
            {"content": "Chunk 2", "token_count": 10, "chunk_index": 1, "metadata": {}}
        ]
        return chunker

    @pytest.fixture
    def mock_embedding_service(self):
        """Create a mock embedding service."""
        service = MagicMock(spec=EmbeddingService)
        service.encode.return_value = np.array([[0.1] * 384, [0.2] * 384])
        return service

    @pytest.fixture
    def ingestion_service(self, mock_chunker, mock_embedding_service):
        """Create a document ingestion service."""
        return DocumentIngestionService(mock_chunker, mock_embedding_service)

    @pytest.mark.asyncio
    async def test_ingest_document(self, ingestion_service):
        """Test document ingestion."""
        mock_db_session = AsyncMock()

        doc_id = await ingestion_service.ingest_document(
            content="Test document content",
            source=DocumentSource.manual,
            title="Test Document",
            db_session=mock_db_session
        )

        assert isinstance(doc_id, str)
        assert len(doc_id) > 0

        # Verify database calls
        assert mock_db_session.add.call_count == 3  # 1 document + 2 chunks
        mock_db_session.commit.assert_called_once()