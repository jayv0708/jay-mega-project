from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from agents import CritiqueAgent, DecompositionAgent, OrchestratorAgent, RAGAgent, SynthesisAgent
from app.context import ContextBudgetManager, SharedContext
from app.events import EventLogger, SSEEvent


class OrchestrationPipeline:
    def __init__(self, event_logger: EventLogger | None = None) -> None:
        self.event_logger = event_logger or EventLogger()
        self.agents = {
            "orchestrator": OrchestratorAgent(),
            "decomposition": DecompositionAgent(),
            "rag": RAGAgent(),
            "critique": CritiqueAgent(),
            "synthesis": SynthesisAgent(),
        }

    async def stream(self, query: str, job_id: UUID | None = None) -> AsyncIterator[SSEEvent]:
        context = SharedContext(query=query, job_id=job_id)
        budget_manager = ContextBudgetManager(
            context,
            total_tokens=10000,
            per_agent_limits={agent_id: agent.max_context_budget for agent_id, agent in self.agents.items()},
        )

        first_event = SSEEvent(
            event_type="HANDOFF",
            agent_id="api",
            data={"job_id": str(context.job_id), "query": query},
            budget_remaining=budget_manager.check_remaining("shared"),
        )
        await self._log(context.job_id, first_event)
        yield first_event

        await self._run_agent("orchestrator", context, budget_manager)
        async for event in self._emit_handoff(context, "orchestrator", "decomposition", budget_manager):
            yield event

        routing = context.metadata.get("routing_decision", {})
        execution_order = routing.get("execution_order", ["decomposition", "rag", "critique", "synthesis"])
        for agent_id in execution_order:
            if agent_id not in self.agents or agent_id == "orchestrator":
                continue
            async for event in self._emit_handoff(context, "orchestrator", agent_id, budget_manager):
                yield event
            await self._run_agent(agent_id, context, budget_manager)
            async for event in self._emit_budget(context, agent_id, budget_manager):
                yield event
            output = context.agent_outputs.get(agent_id)
            if output:
                async for event in self._emit_tokens(context, agent_id, output.output, budget_manager):
                    yield event

        for violation in context.policy_violations:
            event = SSEEvent(
                event_type="POLICY_VIOLATION",
                agent_id="budget-manager",
                data=violation.model_dump(mode="json"),
                budget_remaining=budget_manager.check_remaining("shared"),
            )
            await self._log(context.job_id, event)
            yield event

        final_event = SSEEvent(
            event_type="JOB_COMPLETE",
            agent_id="synthesis",
            data={
                "job_id": str(context.job_id),
                "final_answer": context.agent_outputs.get("synthesis").output if "synthesis" in context.agent_outputs else "",
            },
            budget_remaining=budget_manager.check_remaining("shared"),
        )
        await self._log(context.job_id, final_event)
        yield final_event

    async def _run_agent(self, agent_id: str, context: SharedContext, budget_manager: ContextBudgetManager) -> None:
        await self.agents[agent_id]._execute_with_tracking(context, budget_manager)

    async def _emit_handoff(
        self,
        context: SharedContext,
        from_agent: str,
        to_agent: str,
        budget_manager: ContextBudgetManager,
    ) -> AsyncIterator[SSEEvent]:
        event = SSEEvent(
            event_type="HANDOFF",
            agent_id=from_agent,
            data={"from_agent": from_agent, "to_agent": to_agent},
            budget_remaining=budget_manager.check_remaining("shared"),
        )
        await self._log(context.job_id, event)
        yield event

    async def _emit_budget(
        self,
        context: SharedContext,
        agent_id: str,
        budget_manager: ContextBudgetManager,
    ) -> AsyncIterator[SSEEvent]:
        event = SSEEvent(
            event_type="BUDGET_UPDATE",
            agent_id=agent_id,
            data={key: value.model_dump() | {"remaining_tokens": value.remaining_tokens} for key, value in context.budget_state.items()},
            budget_remaining=budget_manager.check_remaining("shared"),
        )
        await self._log(context.job_id, event)
        yield event

    async def _emit_tokens(
        self,
        context: SharedContext,
        agent_id: str,
        text: str,
        budget_manager: ContextBudgetManager,
    ) -> AsyncIterator[SSEEvent]:
        for token in text.split():
            event = SSEEvent(
                event_type="TOKEN",
                agent_id=agent_id,
                data={"token": token + " "},
                budget_remaining=budget_manager.check_remaining("shared"),
            )
            await self._log(context.job_id, event)
            yield event
            await asyncio.sleep(0)

    async def _log(self, job_id: UUID, event: SSEEvent) -> None:
        await self.event_logger.log_sse_event(job_id, event)
