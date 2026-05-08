"""Orchestration Pipeline as an explicit DAG Executor."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator
from uuid import UUID

from app.context import ContextBudgetManager, SharedContext
from app.events import EventLogger, SSEEvent
from agents.standard_agents import CritiqueAgent, DecompositionAgent, OrchestratorAgent, RAGAgent, SynthesisAgent
from retrieval.retrieval import RetrievalService
from retrieval.embedding import EmbeddingService
from job_queue.broker import JobBroker
from db.db import get_async_session
from db.models import Job, JobStatus

class DAGExecutor:
    def __init__(self, job_id: str | UUID, event_logger: EventLogger | None = None) -> None:
        self.job_id = str(job_id)
        self.event_logger = event_logger or EventLogger()
        self.embedding_service = EmbeddingService()
        self.retrieval_service = RetrievalService(self.embedding_service)

        self.agents = {
            "orchestrator": OrchestratorAgent(),
            "decomposition": DecompositionAgent(),
            "rag": RAGAgent(retrieval_service=self.retrieval_service),
            "critique": CritiqueAgent(),
            "synthesis": SynthesisAgent(),
        }

    async def execute_dag(self, query: str) -> None:
        """Executes the DAG statemachine and persists step state."""
        context = SharedContext(query=query, job_id=self.job_id)
        budget_manager = ContextBudgetManager(
            context,
            total_tokens=10000,
            per_agent_limits={agent_id: agent.max_context_budget for agent_id, agent in self.agents.items()},
        )

        async with get_async_session() as session:
            broker = JobBroker(session)

            # Step 1: Orchestrator Plan
            step = await broker.enqueue_step(self.job_id, "orchestrator", context.model_dump(mode="json"))
            await self._run_agent_and_log("orchestrator", context, budget_manager)
            await broker.complete_step(step.id, context.model_dump(mode="json"))

            # Extract routing
            routing = context.metadata.get("routing_decision", {})
            execution_order = routing.get("selected_agents", ["decomposition", "rag", "critique", "synthesis"])

            # Enqueue remaining steps according to DAG
            for agent_id in execution_order:
                if agent_id not in self.agents or agent_id == "orchestrator":
                    continue
                step = await broker.enqueue_step(self.job_id, agent_id, context.model_dump(mode="json"))
                try:
                    await self._run_agent_and_log(agent_id, context, budget_manager)
                    await broker.complete_step(step.id, context.model_dump(mode="json"))
                except Exception as e:
                    await broker.fail_step(step.id, str(e))
                    raise

            # Final check
            for violation in context.policy_violations:
                event = SSEEvent(
                    event_type="POLICY_VIOLATION",
                    agent_id="budget-manager",
                    data=violation.model_dump(mode="json"),
                    budget_remaining=budget_manager.check_remaining("shared"),
                )
                await self.event_logger.log_sse_event(UUID(self.job_id), event)

            final_event = SSEEvent(
                event_type="JOB_COMPLETE",
                agent_id="synthesis",
                data={
                    "job_id": self.job_id,
                    "final_answer": context.agent_outputs.get("synthesis").output if "synthesis" in context.agent_outputs else "",
                },
                budget_remaining=budget_manager.check_remaining("shared"),
            )
            await self.event_logger.log_sse_event(UUID(self.job_id), final_event)

    async def _run_agent_and_log(self, agent_id: str, context: SharedContext, budget_manager: ContextBudgetManager) -> None:
        event = SSEEvent(
            event_type="HANDOFF",
            agent_id="system",
            data={"to_agent": agent_id},
            budget_remaining=budget_manager.check_remaining("shared"),
        )
        await self.event_logger.log_sse_event(UUID(self.job_id), event)
        
        await self.agents[agent_id]._execute_with_tracking(context, budget_manager)
        
        output = context.agent_outputs.get(agent_id)
        if output:
            event = SSEEvent(
                event_type="TOKEN",
                agent_id=agent_id,
                data={"token": output.output},
                budget_remaining=budget_manager.check_remaining("shared"),
            )
            await self.event_logger.log_sse_event(UUID(self.job_id), event)
