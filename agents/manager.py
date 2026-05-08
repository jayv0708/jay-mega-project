"""Agent orchestration and management."""

from typing import Dict, List, Optional
import logging

from app.context import SharedContext, ContextBudgetManager
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages the execution of agents in a defined order with error handling."""

    def __init__(self) -> None:
        self.agents: Dict[str, BaseAgent] = {}
        self.execution_order: List[str] = []
        self.agent_dependencies: Dict[str, List[str]] = {}  # agent_id -> list of dependency agent_ids

    def register_agent(self, agent: BaseAgent, dependencies: Optional[List[str]] = None) -> None:
        """Register an agent with optional dependencies."""
        self.agents[agent.agent_id] = agent
        self.agent_dependencies[agent.agent_id] = dependencies or []
        self.execution_order.append(agent.agent_id)
        logger.debug(f"Registered agent '{agent.agent_id}' with dependencies {dependencies}")

    def clear(self) -> None:
        """Clear all registered agents."""
        self.agents.clear()
        self.execution_order.clear()
        self.agent_dependencies.clear()

    async def execute_all(
        self, context: SharedContext, budget_manager: ContextBudgetManager, skip_errors: bool = False
    ) -> SharedContext:
        """Execute all agents in order, updating the shared context.
        
        Args:
            context: The shared context to pass between agents
            budget_manager: The budget manager for controlling token consumption
            skip_errors: If True, continue executing agents even if one fails
            
        Returns:
            Updated shared context after all agent executions
        """
        for agent_id in self.execution_order:
            try:
                agent = self.agents[agent_id]
                logger.info(f"Executing agent '{agent_id}'")
                context = await agent._execute_with_tracking(context, budget_manager)
                logger.debug(f"Agent '{agent_id}' completed successfully")
            except Exception as e:
                logger.error(f"Error executing agent '{agent_id}': {e}", exc_info=True)
                if not skip_errors:
                    raise
                # Continue to next agent if skip_errors is True

        return context

    async def execute_order(
        self,
        context: SharedContext,
        budget_manager: ContextBudgetManager,
        execution_order: List[str],
        skip_errors: bool = False,
    ) -> SharedContext:
        for agent_id in execution_order:
            if agent_id not in self.agents:
                if skip_errors:
                    continue
                raise ValueError(f"Agent '{agent_id}' not found")
            context.metadata.setdefault("handoffs", []).append({"to_agent": agent_id})
            context = await self.agents[agent_id]._execute_with_tracking(context, budget_manager)
        return context

    async def execute_agent(
        self, agent_id: str, context: SharedContext, budget_manager: ContextBudgetManager
    ) -> SharedContext:
        """Execute a specific agent by ID.
        
        Args:
            agent_id: The ID of the agent to execute
            context: The shared context
            budget_manager: The budget manager
            
        Returns:
            Updated shared context
        """
        if agent_id not in self.agents:
            raise ValueError(f"Agent '{agent_id}' not found")

        agent = self.agents[agent_id]
        logger.info(f"Executing specific agent '{agent_id}'")
        context = await agent._execute_with_tracking(context, budget_manager)
        return context

    def get_agent_stats(self) -> Dict[str, dict]:
        """Get statistics for all registered agents."""
        return {agent_id: agent.get_stats() for agent_id, agent in self.agents.items()}

    def get_execution_order(self) -> List[str]:
        """Get the execution order of agents."""
        return self.execution_order.copy()
