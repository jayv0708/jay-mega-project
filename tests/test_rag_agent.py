"""Tests for the updated RAG agent with real retrieval."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.standard_agents import RAGAgent
from app.context import SharedContext
from retrieval import RetrievalService, RetrievedChunk


class TestRAGAgent:
    """Test the RAG agent with retrieval service."""

    @pytest.fixture
    def mock_retrieval_service(self):
        """Create a mock retrieval service."""
        service = MagicMock(spec=RetrievalService)
        return service

    @pytest.fixture
    def rag_agent(self, mock_retrieval_service):
        """Create a RAG agent with mock retrieval service."""
        return RAGAgent(retrieval_service=mock_retrieval_service)

    @pytest.mark.asyncio
    async def test_execute_with_retrieval(self, rag_agent, mock_retrieval_service):
        """Test RAG agent execution with retrieval service."""
        # Mock retrieved chunks
        retrieved_chunk = RetrievedChunk(
            chunk_id="chunk1",
            content="Retrieved content for testing",
            document_id="doc1",
            chunk_index=0,
            semantic_score=0.9,
            bm25_score=0.8,
            combined_score=0.85,
            metadata={}
        )

        mock_retrieval_service.retrieve.return_value = [retrieved_chunk]

        context = SharedContext(query="Test query")

        result_context = await rag_agent.execute(context)

        # Verify retrieval was called
        mock_retrieval_service.retrieve.assert_called_once()

        # Verify chunks were added to context
        assert len(result_context.retrieved_chunks) == 1
        assert result_context.retrieved_chunks[0].id == "chunk1"

        # Verify citations were created
        assert len(result_context.citations) == 1
        assert result_context.citations[0].chunk_id == "chunk1"

        # Verify agent output was created
        assert "rag" in result_context.agent_outputs
        output = result_context.agent_outputs["rag"]
        assert "Retrieved content" in output.output

    @pytest.mark.asyncio
    async def test_execute_fallback_to_mock(self):
        """Test RAG agent falls back to mock data when no retrieval service."""
        agent = RAGAgent()  # No retrieval service

        context = SharedContext(query="Test query")

        result_context = await agent.execute(context)

        # Should have mock chunks
        assert len(result_context.retrieved_chunks) == 2
        assert result_context.retrieved_chunks[0].id == "chunk_a"
        assert result_context.retrieved_chunks[1].id == "chunk_b"

    @pytest.mark.asyncio
    async def test_execute_retrieval_returns_empty(self, rag_agent, mock_retrieval_service):
        """Test RAG agent falls back when retrieval returns no results."""
        mock_retrieval_service.retrieve.return_value = []

        context = SharedContext(query="Test query")

        result_context = await rag_agent.execute(context)

        # Should fall back to mock data
        assert len(result_context.retrieved_chunks) == 2
        assert result_context.retrieved_chunks[0].id == "chunk_a"