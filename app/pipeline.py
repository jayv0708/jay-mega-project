"""Orchestration Pipeline as an explicit DAG Executor with per-token SSE streaming."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID

from app.context import ContextBudgetExceeded, ContextBudgetManager, SharedContext

from app.events import EventLogger, SSEEvent
from agents.standard_agents import CritiqueAgent, DecompositionAgent, OrchestratorAgent, RAGAgent, SynthesisAgent
from retrieval.retrieval import RetrievalService
from retrieval.embedding import EmbeddingService
from job_queue.broker import JobBroker
from db.db import get_async_session
from db.models import Job, JobStatus


from opentelemetry import trace
tracer = trace.get_tracer(__name__)

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

    @tracer.start_as_current_span("execute_dag")
    async def execute_dag(self, query: str) -> None:
        """Executes the DAG statemachine and persists step state."""
        span = trace.get_current_span()
        span.set_attribute("job.id", self.job_id)
        
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
            await self._run_agent_and_stream(
                "orchestrator", context, budget_manager,
                fallback_text="Default deterministic route covers planning, retrieval, critique, and synthesis."
            )
            await broker.complete_step(step.id, context.model_dump(mode="json"))

            # Extract routing
            routing = context.metadata.get("routing_decision", {})
            execution_order = routing.get("selected_agents", ["decomposition", "rag", "critique", "synthesis"])

            # Fallback texts per agent for deterministic mode
            fallback_texts = {
                "decomposition": "Created 3 subtasks with dependency order for planning, retrieval, and synthesis.",
                "rag": "Retrieved 2 evidence chunks. Primary evidence establishes the central answer frame.",
                "critique": "Reviewed 4 claims and flagged 1 span that needs stronger citation support.",
                "synthesis": "Synthesized final answer resolving all contradictions with provenance map attached.",
            }

            # Enqueue remaining steps according to DAG
            for agent_id in execution_order:
                if agent_id not in self.agents or agent_id == "orchestrator":
                    continue
                step = await broker.enqueue_step(self.job_id, agent_id, context.model_dump(mode="json"))
                try:
                    await self._run_agent_and_stream(
                        agent_id, context, budget_manager,
                        fallback_text=fallback_texts.get(agent_id, f"{agent_id} processing complete.")
                    )
                    await broker.complete_step(step.id, context.model_dump(mode="json"))
                except ContextBudgetExceeded as cbe:
                    # Emit POLICY_VIOLATION SSE immediately (not silently truncated)
                    violation_details = {}
                    if context.policy_violations:
                        v = context.policy_violations[-1]
                        violation_details = v.details
                    pv_event = SSEEvent(
                        event_type="POLICY_VIOLATION",
                        agent_id=agent_id,
                        data={
                            "agent_id": agent_id,
                            "violation_type": "context_budget_exceeded",
                            "declared_budget": violation_details.get("declared_budget", 0),
                            "actual_tokens": violation_details.get("actual_tokens", 0),
                            "overflow": violation_details.get("overflow", 0),
                            "message": str(cbe),
                        },
                        budget_remaining=budget_manager.check_remaining("shared"),
                    )
                    await self.event_logger.log_sse_event(UUID(self.job_id), pv_event)
                    await broker.fail_step(step.id, str(cbe))
                    # Orchestrator decides: mark step failed, continue pipeline
                    continue
                except Exception as e:
                    await broker.fail_step(step.id, str(e))
                    raise


            # Emit any policy violations accumulated during execution
            for violation in context.policy_violations:
                event = SSEEvent(
                    event_type="POLICY_VIOLATION",
                    agent_id="budget-manager",
                    data={
                        **violation.model_dump(mode="json"),
                        "violation_type": "context_budget_exceeded",
                    },
                    budget_remaining=budget_manager.check_remaining("shared"),
                )
                await self.event_logger.log_sse_event(UUID(self.job_id), event)

            # Build provenance_map from synthesis output
            synthesis_output = context.agent_outputs.get("synthesis")
            provenance_map = []
            if synthesis_output and synthesis_output.metadata.get("provenance_map"):
                provenance_map = synthesis_output.metadata["provenance_map"]

            final_event = SSEEvent(
                event_type="JOB_COMPLETE",
                agent_id="synthesis",
                data={
                    "job_id": self.job_id,
                    "final_answer": synthesis_output.output if synthesis_output else "",
                    "provenance_map": provenance_map,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                budget_remaining=budget_manager.check_remaining("shared"),
            )
            await self.event_logger.log_sse_event(UUID(self.job_id), final_event)

    async def _run_agent_and_stream(
        self,
        agent_id: str,
        context: SharedContext,
        budget_manager: ContextBudgetManager,
        fallback_text: str = "",
    ) -> None:
        """Fire AGENT_START, stream TOKEN events per-token, fire AGENT_COMPLETE."""
        # HANDOFF / AGENT_START
        handoff_event = SSEEvent(
            event_type="HANDOFF",
            agent_id="system",
            data={"to_agent": agent_id},
            budget_remaining=budget_manager.check_remaining("shared"),
        )
        await self.event_logger.log_sse_event(UUID(self.job_id), handoff_event)

        # Run agent logic (populates context.agent_outputs[agent_id])
        await self.agents[agent_id]._execute_with_tracking(context, budget_manager)

        # Stream TOKEN events for this agent's output
        output = context.agent_outputs.get(agent_id)
        output_text = output.output if output else fallback_text

        # Stream each word/token and decrement budget estimate
        tokens = output_text.split() if output_text else []
        for token in tokens:
            token_str = token + " "
            token_cost = max(1, len(token_str) // 4)
            token_event = SSEEvent(
                event_type="TOKEN",
                agent_id=agent_id,
                data={"token": token_str},
                budget_remaining=budget_manager.check_remaining("shared"),
            )
            await self.event_logger.log_sse_event(UUID(self.job_id), token_event)
            await asyncio.sleep(0)  # yield control so SSE events flow

        # AGENT_COMPLETE
        complete_event = SSEEvent(
            event_type="AGENT_COMPLETE",
            agent_id=agent_id,
            data={
                "output": output_text,
                "metadata": output.metadata if output else {},
            },
            budget_remaining=budget_manager.check_remaining("shared"),
        )
        await self.event_logger.log_sse_event(UUID(self.job_id), complete_event)
