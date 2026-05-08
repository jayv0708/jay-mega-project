from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PolicyViolation(BaseModel):
    violation_type: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class BudgetState(BaseModel):
    max_tokens: int = Field(default=4096, ge=0)
    used_tokens: int = Field(default=0, ge=0)
    last_updated: datetime = Field(default_factory=utc_now)

    @property
    def remaining_tokens(self) -> int:
        return max(self.max_tokens - self.used_tokens, 0)

    def consume(self, amount: int) -> None:
        if amount < 0:
            raise ValueError("Budget consumption amount must be non-negative")
        if amount > self.remaining_tokens:
            raise ContextBudgetExceeded("Not enough budget remaining")
        self.used_tokens += amount
        self.last_updated = utc_now()


class SubTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str = "general"
    description: str
    dependencies: list[str] = Field(default_factory=list)
    status: str = "pending"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def task_id(self) -> str:
        return self.id

    @property
    def depends_on(self) -> list[str]:
        return self.dependencies


Subtask = SubTask


class Chunk(BaseModel):
    id: str
    text: str
    source_url: str
    relevance_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        return self.id

    @property
    def source(self) -> str:
        return self.source_url

    @property
    def relevance(self) -> float:
        return self.relevance_score


RetrievedChunk = Chunk


class ToolOutput(BaseModel):
    tool_name: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None
    success: bool = False
    timestamp: datetime = Field(default_factory=utc_now)


class AgentOutput(BaseModel):
    agent_id: str
    output: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class Citation(BaseModel):
    sentence: str = ""
    chunk_id: str
    agent_id: str
    source_url: str | None = None
    start_index: int | None = None
    end_index: int | None = None
    confidence: float | None = None

    @property
    def text(self) -> str:
        return self.sentence

    @property
    def source(self) -> str | None:
        return self.source_url


class Contradiction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    statement_a: str
    agent_a: str
    statement_b: str
    agent_b: str
    severity: str = "medium"
    resolution: str | None = None
    justification: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SharedContext(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    query: str
    subtasks: list[SubTask] = Field(default_factory=list)
    retrieved_chunks: list[Chunk] = Field(default_factory=list)
    tool_outputs: list[ToolOutput] = Field(default_factory=list)
    agent_outputs: dict[str, AgentOutput] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    budget_state: dict[str, BudgetState] = Field(default_factory=dict)
    policy_violations: list[PolicyViolation] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def normalize_job_id(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("job_id") is None:
            values.pop("job_id", None)
        return values

    def touch(self) -> None:
        self.updated_at = utc_now()

    def add_tool_output(self, tool_output: ToolOutput) -> None:
        self.tool_outputs.append(tool_output)
        self.touch()

    def add_agent_output(self, agent_output: AgentOutput) -> None:
        self.agent_outputs[agent_output.agent_id] = agent_output
        self.touch()

    def add_contradiction(self, contradiction: Contradiction) -> None:
        self.contradictions.append(contradiction)
        self.touch()

    def add_policy_violation(
        self,
        violation: PolicyViolation,
        persist: bool = False,
        db_session: "AsyncSession | None" = None,
    ) -> None:
        self.policy_violations.append(violation)
        self.touch()
        if persist and db_session is not None:
            self._persist_policy_violation(db_session, violation)

    def _persist_policy_violation(self, db_session: "AsyncSession", violation: PolicyViolation) -> None:
        from db.models import AgentEvent

        event = AgentEvent(
            job_id=self.job_id,
            agent_id="budget-manager",
            event_type="POLICY_VIOLATION",
            policy_violation=True,
            payload=violation.model_dump(mode="json"),
        )
        db_session.add(event)
        commit_result = db_session.commit()
        if inspect.isawaitable(commit_result):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(commit_result)
            else:
                loop.create_task(commit_result)

    def get_agent_budget_state(self, agent_id: str, max_tokens: int = 4096) -> BudgetState:
        if agent_id not in self.budget_state:
            self.budget_state[agent_id] = BudgetState(max_tokens=max_tokens)
        return self.budget_state[agent_id]


class ContextBudgetExceeded(Exception):
    pass


class ContextBudgetManager:
    def __init__(
        self,
        shared_context: SharedContext,
        total_tokens: int = 4096,
        per_agent_limits: dict[str, int] | None = None,
        db_session: "AsyncSession | None" = None,
    ) -> None:
        self.shared_context = shared_context
        self.db_session = db_session
        self.total_tokens = total_tokens
        self.per_agent_limits = per_agent_limits or {}
        self.shared_context.get_agent_budget_state("shared", total_tokens)

    def register_agent(self, agent_id: str, max_context_budget: int) -> None:
        limit = self.per_agent_limits.get(agent_id, max_context_budget)
        self.shared_context.get_agent_budget_state(agent_id, limit).max_tokens = limit

    def check_remaining(self, agent_id: str, token_cost: int = 0) -> int | bool:
        state = self.shared_context.get_agent_budget_state(
            agent_id,
            self.per_agent_limits.get(agent_id, self.total_tokens),
        )
        if token_cost < 0:
            raise ValueError("Token cost must be non-negative")
        if token_cost and token_cost > state.remaining_tokens:
            self._handle_over_budget(agent_id, token_cost, state.remaining_tokens)
            return False
        return state.remaining_tokens if token_cost == 0 else True

    def consume(self, agent_id: str, token_cost: int = 1) -> None:
        state = self.shared_context.get_agent_budget_state(
            agent_id,
            self.per_agent_limits.get(agent_id, self.total_tokens),
        )
        shared = self.shared_context.get_agent_budget_state("shared", self.total_tokens)
        if token_cost > state.remaining_tokens or token_cost > shared.remaining_tokens:
            self._handle_over_budget(agent_id, token_cost, min(state.remaining_tokens, shared.remaining_tokens))
            return
        state.consume(token_cost)
        shared.consume(token_cost)
        self.shared_context.touch()

    def ensure_can_add(self, agent_id: str, payload: Any) -> bool:
        token_cost = self.estimate_tokens(payload)
        if self.check_remaining(agent_id, token_cost=token_cost) is True:
            return True
        return False

    def estimate_tokens(self, payload: Any) -> int:
        serialized = json.dumps(payload, default=str, sort_keys=True)
        return max(1, len(serialized) // 4)

    def _handle_over_budget(self, agent_id: str, requested_tokens: int, remaining_tokens: int) -> None:
        self.compress_context(agent_id)
        state = self.shared_context.get_agent_budget_state(agent_id)
        shared = self.shared_context.get_agent_budget_state("shared")
        if requested_tokens <= min(state.remaining_tokens, shared.remaining_tokens):
            return
        declared_budget = self.per_agent_limits.get(agent_id, self.total_tokens)
        actual_tokens = declared_budget - remaining_tokens + requested_tokens
        overflow = actual_tokens - declared_budget
        violation = PolicyViolation(
            violation_type="context_budget_exceeded",
            message=f"Agent '{agent_id}' attempted to add context beyond its declared budget.",
            details={
                "agent_id": agent_id,
                "violation_type": "context_budget_exceeded",
                "declared_budget": declared_budget,
                "actual_tokens": actual_tokens,
                "overflow": max(0, overflow),
                "requested_tokens": requested_tokens,
                "remaining_tokens_before_compression": remaining_tokens,
                "remaining_tokens_after_compression": min(state.remaining_tokens, shared.remaining_tokens),
            },
        )
        self.shared_context.add_policy_violation(violation, persist=True, db_session=self.db_session)
        raise ContextBudgetExceeded(violation.message)


    def compress_context(self, triggering_agent_id: str) -> SharedContext:
        """Lossless for structured fields, lossy only for narrative agent outputs."""
        for agent_id, output in list(self.shared_context.agent_outputs.items()):
            if len(output.output) <= 320:
                continue
            compressed = output.output[:280].rstrip() + " ... [compressed narrative]"
            self.shared_context.agent_outputs[agent_id] = output.model_copy(update={"output": compressed})
        self.shared_context.metadata.setdefault("compression_events", []).append(
            {
                "triggering_agent_id": triggering_agent_id,
                "timestamp": utc_now().isoformat(),
                "mode": "lossless_structured_lossy_narrative",
            }
        )
        self.shared_context.touch()
        return self.shared_context
