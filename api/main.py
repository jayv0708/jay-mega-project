from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.events import EventLogger
from app.pipeline import DAGExecutor
from db.db import get_async_session
from db.models import Job, JobStatus
from eval.meta_loop import decide_rewrite, get_rewrite, list_rewrites_from_db, load_rewrites
from eval.runner import latest_run, run_all_cases, run_all_cases_async

app = FastAPI(title="Real-Time Multi-Agent LLM Orchestration System", version="0.7.0")
event_logger = EventLogger()


class QueryRequest(BaseModel):
    query: str


class RewriteDecisionRequest(BaseModel):
    decision: str          # "approved" | "rejected"
    decided_by: str = ""   # who is approving/rejecting


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


from opentelemetry import trace

tracer = trace.get_tracer(__name__)

# ── Endpoint 1 ───────────────────────────────────────────────────
@app.post("/query")
async def query(request: QueryRequest):
    if not request.query.strip():
        return error_response("EMPTY_QUERY", "Query must not be empty.")

    job_id = str(uuid.uuid4())

    with tracer.start_as_current_span("api_query_endpoint") as span:
        span.set_attribute("job.id", job_id)
        span.set_attribute("query.length", len(request.query))
        
        async with get_async_session() as session:
            job = Job(id=job_id, query=request.query, status=JobStatus.pending)
            session.add(job)
            await session.commit()

        executor = DAGExecutor(job_id=job_id, event_logger=event_logger)
        task = asyncio.create_task(executor.execute_dag(request.query))


    async def event_stream():
        last_index = 0
        while True:
            events = event_logger.memory_events_by_job.get(job_id, [])
            for event in events[last_index:]:
                yield event.encode()
            last_index = len(events)

            if events and events[-1].event_type == "JOB_COMPLETE":
                break
            if task.done() and last_index == len(events):
                break

            await asyncio.sleep(0.05)  # tighter poll for lower token latency

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Endpoint 2 ───────────────────────────────────────────────────
@app.get("/jobs/{job_id}/trace")
async def get_trace(job_id: UUID) -> dict[str, Any]:
    memory_trace = [
        event.model_dump(mode="json")
        for event in event_logger.memory_events_by_job.get(str(job_id), [])
    ]
    db_trace = await _load_db_trace(job_id)
    trace = db_trace or memory_trace
    return {"job_id": str(job_id), "trace": trace}


# ── Endpoint 3 ───────────────────────────────────────────────────
@app.get("/evals/latest")
async def get_latest_eval() -> dict[str, Any]:
    run = latest_run() or run_all_cases()
    summary = run["summary"]
    by_dim = summary.get("by_dimension", {})
    # Enrich by_dimension with min/worst_case_id
    enriched_dim: dict[str, Any] = {}
    for dim, info in by_dim.items():
        failed = info.get("failed_cases", [])
        avg = info.get("avg_score", 0.0)
        enriched_dim[dim] = {
            "avg": avg,
            "min": min(
                (r["scores"][dim]["score"] for r in run.get("cases", []) if dim in r.get("scores", {})),
                default=avg,
            ),
            "worst_case_id": failed[0] if failed else None,
        }
    return {
        "run_id": run["run_id"],
        "run_at": run.get("run_at") or datetime.now(timezone.utc).isoformat(),
        "by_category": summary.get("by_category", {}),
        "by_dimension": enriched_dim,
    }


# ── Endpoint 4 ───────────────────────────────────────────────────
@app.post("/rewrites/{rewrite_id}/decision")
async def post_rewrite_decision(rewrite_id: str, request: RewriteDecisionRequest):
    try:
        rewrite = await decide_rewrite(
            rewrite_id,
            request.decision,
            request.decided_by,
            latest_run(),
        )
        return rewrite
    except KeyError:
        return error_response("REWRITE_NOT_FOUND", f"Rewrite {rewrite_id} was not found.", status_code=404)
    except ValueError as exc:
        return error_response("INVALID_REWRITE_DECISION", str(exc), status_code=400)


# ── Endpoint 5 ───────────────────────────────────────────────────
@app.post("/evals/rerun-failures")
async def rerun_failures() -> dict[str, Any]:
    run = latest_run() or run_all_cases()
    rerun = await run_all_cases_async(only_failed_from=run)
    return {
        "run_id": rerun["run_id"],
        "rerun_case_count": rerun["total_cases"],
        "summary": rerun["summary"],
    }


# ── Internal helpers ─────────────────────────────────────────────
async def _load_db_trace(job_id: UUID) -> list[dict[str, Any]]:
    try:
        from db.db import get_async_session
        from db.models import AgentEvent, ToolCall
        from sqlalchemy import select

        session = get_async_session()
        async with session:
            event_rows = (
                await session.execute(select(AgentEvent).where(AgentEvent.job_id == job_id))
            ).scalars().all()
            tool_rows = (
                await session.execute(select(ToolCall).where(ToolCall.job_id == job_id))
            ).scalars().all()

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
