import pytest

from app.context import ContextBudgetManager, ContextBudgetExceeded, SharedContext


def test_context_budget_consumption_passes_when_within_limit():
    context = SharedContext(query="What is the capital of France?")
    budget_manager = ContextBudgetManager(context, total_tokens=10)

    assert budget_manager.check_remaining("agent_a", token_cost=3)
    budget_manager.consume("agent_a", token_cost=3)

    assert context.budget_state["shared"].used_tokens == 3
    assert context.budget_state["shared"].remaining_tokens == 7
    assert context.policy_violations == []


def test_context_budget_consumption_fails_when_over_capacity():
    context = SharedContext(query="Summarize this document.")
    budget_manager = ContextBudgetManager(context, total_tokens=5)

    budget_manager.consume("agent_a", token_cost=3)
    with pytest.raises(ContextBudgetExceeded):
        budget_manager.consume("agent_a", token_cost=3)

    assert len(context.policy_violations) == 1
    assert context.policy_violations[0].violation_type == "CONTEXT_BUDGET_EXCEEDED"


def test_agent_specific_limit_is_enforced():
    context = SharedContext(query="Generate a plan.")
    budget_manager = ContextBudgetManager(
        context,
        total_tokens=10,
        per_agent_limits={"agent_a": 5},
    )

    budget_manager.consume("agent_a", token_cost=5)
    with pytest.raises(ContextBudgetExceeded):
        budget_manager.consume("agent_a", token_cost=1)

    assert len(context.policy_violations) == 1
    assert context.policy_violations[0].violation_type == "CONTEXT_BUDGET_EXCEEDED"
