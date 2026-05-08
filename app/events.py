from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


SSE_EVENT_TYPES = {
    "TOKEN",
    "TOOL_CALL_START",
    "TOOL_CALL_END",
    "HANDOFF",
    "BUDGET_UPDATE",
    "POLICY_VIOLATION",
    "JOB_COMPLETE",
}


class SSEEvent(BaseModel):
    event_type: str
    agent_id: str
    data: Any
    budget_remaining: int
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def encode(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class EventLogger:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory
        self.memory_events: list[SSEEvent] = []
        self.memory_events_by_job: dict[str, list[SSEEvent]] = {}

    async def log_sse_event(self, job_id: UUID, event: SSEEvent, *, latency_ms: int | None = None) -> None:
        self.memory_events.append(event)
        self.memory_events_by_job.setdefault(str(job_id), []).append(event)
        if self.session_factory is None:
            return
        try:
            from db.models import AgentEvent

            session = self.session_factory()
            async with session:
                db_event = AgentEvent(
                    job_id=job_id,
                    agent_id=event.agent_id,
                    event_type=event.event_type,
                    input_hash=stable_hash({"event_type": event.event_type, "agent_id": event.agent_id}),
                    output_hash=stable_hash(event.data),
                    latency_ms=latency_ms,
                    token_count=1 if event.event_type == "TOKEN" else None,
                    policy_violation=event.event_type == "POLICY_VIOLATION",
                    payload=event.model_dump(mode="json"),
                )
                session.add(db_event)
                await session.commit()
        except Exception:
            return
