from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.events import EventLogger
from app.pipeline import OrchestrationPipeline


app = FastAPI(title="Real-Time Multi-Agent LLM Orchestration System", version="0.6.0")
event_logger = EventLogger()


class QueryRequest(BaseModel):
    query: str


def error_response(error_code: str, message: str, job_id: str | None = None, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": message,
            "job_id": job_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.post("/query")
async def query(request: QueryRequest):
    if not request.query.strip():
        return error_response("EMPTY_QUERY", "Query must not be empty.")

    pipeline = OrchestrationPipeline(event_logger=event_logger)

    async def event_stream():
        async for event in pipeline.stream(request.query):
            yield event.encode()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/jobs/{job_id}/trace")
async def get_trace(job_id: UUID) -> dict[str, Any]:
    memory_trace = [
        event.model_dump(mode="json")
        for event in event_logger.memory_events_by_job.get(str(job_id), [])
    ]
    db_trace = await _load_db_trace(job_id)
    return {"job_id": str(job_id), "trace": db_trace or memory_trace}


async def _load_db_trace(job_id: UUID) -> list[dict[str, Any]]:
    try:
        from db.db import get_async_session
        from db.models import AgentEvent, ToolCall
        from sqlalchemy import select

        session = get_async_session()
        async with session:
            event_rows = (await session.execute(select(AgentEvent).where(AgentEvent.job_id == job_id))).scalars().all()
            tool_rows = (await session.execute(select(ToolCall).where(ToolCall.job_id == job_id))).scalars().all()
        trace = [
            {
                "kind": "agent_event",
                "timestamp": row.ts.isoformat(),
                "agent_id": row.agent_id,
                "event_type": row.event_type,
                "payload": row.payload,
                "input_hash": row.input_hash,
                "output_hash": row.output_hash,
                "latency_ms": row.latency_ms,
                "token_count": row.token_count,
                "policy_violation": row.policy_violation,
            }
            for row in event_rows
        ]
        trace.extend(
            {
                "kind": "tool_call",
                "timestamp": row.ts.isoformat(),
                "agent_id": row.agent_id,
                "tool_name": row.tool_name,
                "input": row.input,
                "output": row.output,
                "latency_ms": row.latency_ms,
                "retry_num": row.retry_num,
                "accepted": row.accepted,
            }
            for row in tool_rows
        )
        return sorted(trace, key=lambda item: item["timestamp"])
    except Exception:
        return []


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    return error_response("HTTP_ERROR", str(exc.detail), status_code=exc.status_code)
