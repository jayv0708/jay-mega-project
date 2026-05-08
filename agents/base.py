from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from typing import Any

from app.context import ContextBudgetManager, SharedContext


class BaseAgent(ABC):
    """Base class for agents mediated by the orchestrator through SharedContext."""

    def __init__(self, agent_id: str, max_context_budget: int = 2048) -> None:
        self.agent_id = agent_id
        self.max_context_budget = max_context_budget
        self.execution_count = 0
        self.total_latency_ms = 0
        self.context_manager: ContextBudgetManager | None = None

    @abstractmethod
    async def execute(self, context: SharedContext) -> SharedContext:
        raise NotImplementedError

    def declare_budget(self, context: SharedContext) -> int:
        """Explicitly declare the max context budget before execution."""
        return self.max_context_budget

    async def _execute_with_tracking(
        self,
        context: SharedContext,
        budget_manager: ContextBudgetManager | None = None,
    ) -> SharedContext:
        start_time = time.perf_counter()
        self.execution_count += 1
        
        # Explicitly declare budget before execution
        declared_budget = self.declare_budget(context)
        
        self.context_manager = budget_manager or ContextBudgetManager(context)
        self.context_manager.register_agent(self.agent_id, declared_budget)
        self.context_manager.check_remaining(self.agent_id)

        try:
            return await self.execute(context)
        finally:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            self.total_latency_ms += latency_ms

    def check_can_add(self, payload: Any) -> None:
        if self.context_manager is None:
            raise RuntimeError("Agent must be executed through the orchestrator or tracking wrapper.")
        self.context_manager.ensure_can_add(self.agent_id, payload)

    def consume_budget(self, token_cost: int) -> None:
        if self.context_manager is None:
            raise RuntimeError("Agent must be executed through the orchestrator or tracking wrapper.")
        self.context_manager.consume(self.agent_id, token_cost)

    def _hash_content(self, content: str | dict[str, Any]) -> str:
        if isinstance(content, dict):
            content_str = json.dumps(content, sort_keys=True, default=str)
        else:
            content_str = content
        return hashlib.sha256(content_str.encode("utf-8")).hexdigest()

    def get_stats(self) -> dict[str, Any]:
        avg_latency = self.total_latency_ms / max(self.execution_count, 1)
        return {
            "agent_id": self.agent_id,
            "execution_count": self.execution_count,
            "total_latency_ms": self.total_latency_ms,
            "avg_latency_ms": avg_latency,
        }
