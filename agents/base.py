from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.context import SharedContext


class BaseAgent(ABC):
    agent_id: str
    max_context_budget: int

    def __init__(self, agent_id: str, max_context_budget: int) -> None:
        self.agent_id = agent_id
        self.max_context_budget = max_context_budget

    @abstractmethod
    async def execute(self, context: "SharedContext") -> "SharedContext":
        raise NotImplementedError
