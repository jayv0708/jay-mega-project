import pytest

from app.context import SharedContext, ContextBudgetManager
from agents import (
    AgentManager,
    RetrievalAgent,
    CompressionAgent,
    VerificationAgent,
    RefinementAgent,
    OrchestratorAgent,
    DecompositionAgent,
    RAGAgent,
    CritiqueAgent,
    SynthesisAgent,
)


@pytest.mark.asyncio
async def test_agent_manager_executes_all_agents():
    """Test that AgentManager can execute all registered agents."""
    context = SharedContext(query="What is machine learning?")
    budget_manager = ContextBudgetManager(context, total_tokens=10000)

    manager = AgentManager()
    manager.register_agent(RetrievalAgent())
    manager.register_agent(CompressionAgent())
    manager.register_agent(VerificationAgent())
    manager.register_agent(RefinementAgent())

    result = await manager.execute_all(context, budget_manager)

    # Check that all agents executed and added output
    assert len(result.agent_outputs) == 4
    assert "retrieval" in result.agent_outputs
    assert "compression" in result.agent_outputs
    assert "verification" in result.agent_outputs
    assert "refinement" in result.agent_outputs


@pytest.mark.asyncio
async def test_retrieval_agent_creates_chunks():
    """Test that RetrievalAgent creates retrieved chunks."""
    context = SharedContext(query="What is Python?")
    budget_manager = ContextBudgetManager(context, total_tokens=5000)

    agent = RetrievalAgent()
    result = await agent._execute_with_tracking(context, budget_manager)

    assert len(result.retrieved_chunks) > 0
    assert result.retrieved_chunks[0].chunk_id == "chunk_001"


@pytest.mark.asyncio
async def test_compression_agent_creates_citations():
    """Test that CompressionAgent creates citations."""
    context = SharedContext(query="Test query")
    budget_manager = ContextBudgetManager(context, total_tokens=5000)

    # First run retrieval to get chunks
    retrieval = RetrievalAgent()
    context = await retrieval._execute_with_tracking(context, budget_manager)

    # Then run compression
    compression = CompressionAgent()
    result = await compression._execute_with_tracking(context, budget_manager)

    assert len(result.citations) > 0
    assert result.citations[0].agent_id == "compression"


@pytest.mark.asyncio
async def test_agent_budget_consumption():
    """Test that agents consume budget correctly."""
    context = SharedContext(query="Test budget")
    budget_manager = ContextBudgetManager(context, total_tokens=200)

    agent = RetrievalAgent()
    await agent._execute_with_tracking(context, budget_manager)

    # Budget should be consumed (50 tokens)
    assert context.budget_state["shared"].used_tokens > 0
    assert context.budget_state["shared"].remaining_tokens < 200


@pytest.mark.asyncio
async def test_agent_execution_statistics():
    """Test that agent statistics are tracked."""
    context = SharedContext(query="Test stats")
    budget_manager = ContextBudgetManager(context, total_tokens=5000)

    agent = RetrievalAgent()
    await agent._execute_with_tracking(context, budget_manager)
    await agent._execute_with_tracking(context, budget_manager)

    stats = agent.get_stats()

    assert stats["execution_count"] == 2
    assert stats["total_latency_ms"] >= 0  # May be 0 for fast tests
    assert stats["avg_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_required_agents_produce_routed_cited_synthesis():
    context = SharedContext(query="Explain the system briefly")
    budget_manager = ContextBudgetManager(context, total_tokens=10000)

    for agent in [OrchestratorAgent(), DecompositionAgent(), RAGAgent(), CritiqueAgent(), SynthesisAgent()]:
        context = await agent._execute_with_tracking(context, budget_manager)

    assert "routing_decision" in context.metadata
    assert len(context.subtasks) >= 3
    assert len(context.retrieved_chunks) >= 2
    assert len(context.citations) >= 2
    assert "claim_scores" in context.agent_outputs["critique"].metadata
    assert "provenance_map" in context.agent_outputs["synthesis"].metadata
