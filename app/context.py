from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from db.models import AgentEvent


class PolicyViolation(BaseModel):
    violation_type: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContextBudgetState(BaseModel):
    total_tokens: int = Field(default=4096, ge=0)
    used_tokens: int = Field(default=0, ge=0)
    remaining_tokens: int = Field(default=4096, ge=0)
    reserved_tokens: int = Field(default=0, ge=0)
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    def normalize_remaining(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        total = values.get("total_tokens", 4096)
        used = values.get("used_tokens", 0)
        values["remaining_tokens"] = max(total - used, 0)
        return values

    def can_consume(self, amount: int) -> bool:
        return amount <= self.remaining_tokens

    def consume(self, amount: int) -> None:
        if amount < 0:
            raise ValueError("Budget consumption amount must be non-negative")
        if not self.can_consume(amount):
            raise ValueError("Not enough budget remaining")
        self.used_tokens += amount
        self.remaining_tokens = max(self.total_tokens - self.used_tokens, 0)
        self.last_updated = datetime.utcnow()


class RetrievedChunk(BaseModel):
    chunk_id: str
    source: str
    text: str
    relevance: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolOutput(BaseModel):
    tool_name: str
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    output_payload: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: Optional[int] = None
    success: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentOutput(BaseModel):
    agent_id: str
    output: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Citation(BaseModel):
    source: str
    text: str
    start_index: Optional[int] = None
    end_index: Optional[int] = None
    confidence: Optional[float] = None


class Subtask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    status: str = Field(default="pending")
    depends_on: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SharedContext(BaseModel):
    context_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: Optional[str] = None
    query: str
    subtasks: List[Subtask] = Field(default_factory=list)
    retrieved_chunks: List[RetrievedChunk] = Field(default_factory=list)
    tool_outputs: List[ToolOutput] = Field(default_factory=list)
    agent_outputs: List[AgentOutput] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)
    budget_state: ContextBudgetState = Field(default_factory=ContextBudgetState)
    policy_violations: List[PolicyViolation] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_tool_output(self, tool_output: ToolOutput) -> None:
        self.tool_outputs.append(tool_output)
        self.touch()

    def add_agent_output(self, agent_output: AgentOutput) -> None:
        self.agent_outputs.append(agent_output)
        self.touch()

    def add_policy_violation(
        self,
        violation: PolicyViolation,
        persist: bool = False,
        db_session: Optional[Session] = None,
    ) -> None:
        self.policy_violations.append(violation)
        self.touch()
        if persist and db_session is not None and self.job_id is not None:
            self._persist_policy_violation(db_session, violation)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def _persist_policy_violation(self, db_session: Session, violation: PolicyViolation) -> None:
        event = AgentEvent(
            job_id=self.job_id,
            agent_id="budget-manager",
            event_type="POLICY_VIOLATION",
            payload=violation.model_dump(),
            input_hash=None,
            output_hash=None,
            latency_ms=None,
            token_count=None,
            policy_violations=[violation.model_dump()],
        )
        db_session.add(event)
        db_session.commit()


class ContextBudgetExceeded(Exception):
    pass


class ContextBudgetManager:
    def __init__(
        self,
        shared_context: SharedContext,
        total_tokens: int = 4096,
        per_agent_limits: Optional[Dict[str, int]] = None,
        db_session: Optional[Session] = None,
    ) -> None:
        self.shared_context = shared_context
        self.db_session = db_session
        self.per_agent_limits = per_agent_limits or {}
        self.agent_usage: Dict[str, int] = {}
        self.shared_context.budget_state.total_tokens = total_tokens
        self.shared_context.budget_state.remaining_tokens = max(
            total_tokens - self.shared_context.budget_state.used_tokens, 0
        )

    def check_remaining(self, agent_id: str, token_cost: int = 1) -> bool:
        if token_cost < 0:
            raise ValueError("Token cost must be non-negative")

        agent_used = self.agent_usage.get(agent_id, 0)
        agent_limit = self.per_agent_limits.get(agent_id, self.shared_context.budget_state.total_tokens)

        if token_cost > self.shared_context.budget_state.remaining_tokens:
            violation = PolicyViolation(
                violation_type="BUDGET_OVERFLOW",
                message=f"Agent '{agent_id}' exceeded the shared context budget.",
                details={
                    "requested_tokens": token_cost,
                    "remaining_tokens": self.shared_context.budget_state.remaining_tokens,
                },
            )
            self.shared_context.add_policy_violation(
                violation, persist=True, db_session=self.db_session
            )
            raise ContextBudgetExceeded(violation.message)

        if agent_used + token_cost > agent_limit:
            violation = PolicyViolation(
                violation_type="AGENT_BUDGET_OVERFLOW",
                message=f"Agent '{agent_id}' exceeded its configured budget limit.",
                details={
                    "agent_used": agent_used,
                    "agent_limit": agent_limit,
                    "requested_tokens": token_cost,
                },
            )
            self.shared_context.add_policy_violation(
                violation, persist=True, db_session=self.db_session
            )
            raise ContextBudgetExceeded(violation.message)

        return True

    def consume(self, agent_id: str, token_cost: int = 1) -> None:
        self.check_remaining(agent_id, token_cost)
        self.agent_usage[agent_id] = self.agent_usage.get(agent_id, 0) + token_cost
        self.shared_context.budget_state.consume(token_cost)
        self.shared_context.touch()
