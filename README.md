# Multi-Agent LLM Orchestration System

A production-grade, evaluation-driven multi-agent orchestration platform built with **FastAPI**, **PostgreSQL**, and **Docker**. Designed to be **locally runnable in under 5 minutes** without external services beyond a Docker daemon.

No LangChain. No LlamaIndex. No magic frameworks. Every component justifies its operational cost.

---

## Quick Start

```bash
# Copy environment config
cp .env.example .env    # then set ANTHROPIC_API_KEY

# Start everything
docker compose up
```

- API: `http://localhost:8000/docs` (exactly 5 endpoints)
- Log UI: `http://localhost:8080`
- PostgreSQL: `localhost:5432`

Without `ANTHROPIC_API_KEY`, the system uses deterministic fallbacks — orchestration, critique, and synthesis all run locally.

---

## Architecture

```
  ┌─────────────────────────────────────────────────────────┐
  │                        CLIENT                           │
  └───────────────────────┬─────────────────────────────────┘
                          │  POST /query  (SSE stream)
                          ▼
  ┌─────────────────────────────────────────────────────────┐
  │                     FastAPI (API)                       │
  │  • Validates input                                      │
  │  • Creates Job record                                   │
  │  • Fires asyncio.create_task → DAGExecutor              │
  │  • Returns inline SSE stream (no separate endpoint)     │
  └───────────────────────┬─────────────────────────────────┘
                          │  persists to
                          ▼
  ┌─────────────────────────────────────────────────────────┐
  │          PostgreSQL (jobs + job_steps queue)             │
  │   SKIP LOCKED ensures atomic, crash-safe consumption    │
  └───────────────────────┬─────────────────────────────────┘
                          │  reads by
                          ▼
  ┌─────────────────────────────────────────────────────────┐
  │                  DAGExecutor                            │
  │                                                         │
  │  OrchestratorAgent ──emits──▶ DAG Plan JSON             │
  │    {selected_agents, estimated_tokens, confidence, ...} │
  │                                                         │
  │  ┌──────────┐  ┌──────┐  ┌─────────┐  ┌──────────┐    │
  │  │Decompose │→ │ RAG  │→ │Critique │→ │Synthesis │    │
  │  └──────────┘  └──────┘  └─────────┘  └──────────┘    │
  │                   │                                     │
  │           Hybrid Search (pgvector + tsvector)           │
  │           Reciprocal Rank Fusion at SQL level           │
  │           Retrieval Poison scan per chunk               │
  └───────────────────────┬─────────────────────────────────┘
                          │
  ┌───────────────────────▼─────────────────────────────────┐
  │           Observability Layer                            │
  │  • OpenTelemetry trace_id + span_id on every event       │
  │  • structlog JSON output                                 │
  │  • EventLogger persists to PostgreSQL agent_events      │
  └─────────────────────────────────────────────────────────┘
```

---

## Execution Lifecycle

1. `POST /query` receives `{query: str}`
2. A `Job` row is written to PostgreSQL (`status=pending`)
3. `DAGExecutor.execute_dag()` fires as a background task
4. **Orchestrator** LLM call emits a DAG plan (or deterministic fallback)
5. Steps are enqueued into `job_steps` via `JobBroker` (SKIP LOCKED)
6. Each agent executes, writing its output to `SharedContext`
7. `RAGAgent` performs hybrid SQL search; every chunk is poison-scanned
8. `CritiqueAgent` scores all claims; contradictions are logged
9. `SynthesisAgent` resolves contradictions, builds `provenance_map`
10. `JOB_COMPLETE` SSE event terminates the stream
11. All events include OpenTelemetry `trace_id` + `span_id`

---

## Orchestration: DAG Planner Schema

The `OrchestratorAgent` must emit exactly:

```json
{
  "subtasks": [{"id": "task_rag", "description": "...", "dependencies": []}],
  "dependencies": [],
  "selected_agents": ["decomposition", "rag", "critique", "synthesis"],
  "required_tools": ["web_search"],
  "estimated_tokens": 2800,
  "estimated_cost": 0.04,
  "confidence": 0.92,
  "routing_justification": "Query requires evidence retrieval and contradiction resolution.",
  "rejected_alternatives": ["skip_critique"]
}
```

The `DAGExecutor` reads `selected_agents` to dynamically enqueue only the steps needed — simpler queries can skip `critique`.

---

## Retrieval Flow

```
Query
  │
  ├── pgvector cosine similarity (semantic)
  ├── tsvector websearch_to_tsquery (keyword)
  └── Reciprocal Rank Fusion (RRF) CTE in SQL
        │
        └── Top-K chunks → Poison scan → Citations → Context
```

Every retrieved chunk is inspected for **indirect prompt injection** (retrieval poisoning) before entering `SharedContext`. Poisoned chunks are dropped and logged.

---

## API Endpoints (Exactly 5)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/query` | Submit query; returns SSE stream of execution events |
| `GET` | `/jobs/{job_id}/trace` | Full execution trace (agent events + tool calls) |
| `GET` | `/evals/latest` | Latest eval run summary by category and dimension |
| `POST` | `/rewrites/{rewrite_id}/decision` | Approve or reject a proposed prompt rewrite |
| `POST` | `/evals/rerun-failures` | Re-run only the cases that failed in the latest eval |

All errors return:
```json
{"error_code": "CODE", "message": "...", "job_id": null, "timestamp": "ISO8601"}
```

---

## Example SSE Event Trace

```json
{"event_type":"HANDOFF","agent_id":"system","data":{"to_agent":"decomposition"},"budget_remaining":9900,"trace_id":"4bf92f3577b34da6","span_id":"00f067aa0ba902b7","timestamp":"2026-05-08T11:45:00Z"}
{"event_type":"TOKEN","agent_id":"decomposition","data":{"token":"Created "},"budget_remaining":9899,"trace_id":"4bf92f3577b34da6","span_id":"1a2b3c4d5e6f7890","timestamp":"2026-05-08T11:45:00Z"}
{"event_type":"TOKEN","agent_id":"decomposition","data":{"token":"3 "},"budget_remaining":9898,"trace_id":"4bf92f3577b34da6","span_id":"1a2b3c4d5e6f7891","timestamp":"2026-05-08T11:45:00Z"}
{"event_type":"TOKEN","agent_id":"decomposition","data":{"token":"subtasks "},"budget_remaining":9897,"trace_id":"4bf92f3577b34da6","span_id":"1a2b3c4d5e6f7892","timestamp":"2026-05-08T11:45:01Z"}
{"event_type":"AGENT_COMPLETE","agent_id":"decomposition","data":{"output":"Created 3 subtasks..."},"budget_remaining":9780,"trace_id":"4bf92f3577b34da6","span_id":"1a2b3c4d5e6f7893","timestamp":"2026-05-08T11:45:01Z"}
{"event_type":"HANDOFF","agent_id":"system","data":{"to_agent":"rag"},"budget_remaining":9780,"trace_id":"4bf92f3577b34da6","span_id":"...","timestamp":"..."}
{"event_type":"TOKEN","agent_id":"rag","data":{"token":"Retrieved "},"budget_remaining":9779,"trace_id":"4bf92f3577b34da6","span_id":"...","timestamp":"..."}
{"event_type":"AGENT_COMPLETE","agent_id":"rag","data":{"output":"Retrieved 2 evidence chunks..."},"budget_remaining":9650,"trace_id":"4bf92f3577b34da6","span_id":"...","timestamp":"..."}
{"event_type":"JOB_COMPLETE","agent_id":"synthesis","data":{"job_id":"...","final_answer":"PostgreSQL is...","provenance_map":[...]},"budget_remaining":9000,"trace_id":"4bf92f3577b34da6","span_id":"...","timestamp":"..."}
```

---

## Security Model

**Defence in depth** — security is not a single gate but a layered pipeline.

| Layer | Mechanism |
|-------|-----------|
| Tool input inspection | `tools/security.py` — heuristic regex scan for 10+ injection patterns |
| Shell injection | Blocked before `CodeSandboxTool` executes |
| Retrieval poisoning | Every chunk scanned for embedded injection payloads |
| Container sandboxing | Docker: `network_mode=none`, `read_only=True`, `mem_limit=128m`, `pids_limit=10` |
| Non-root execution | Container runs as UID 1000 |
| Query parameterisation | All SQL uses `$1` placeholders — no string concatenation |
| Audit logging | Every blocked request is logged with `structlog` JSON |
| Docker socket scoping | Only the worker service mounts /var/run/docker.sock; the API has no container access |


Adversarial tests are in `tests/test_security.py`.

---

## Evaluation Methodology

The evaluation harness (`eval/runner.py`) uses **LLM-as-a-Judge** via Anthropic Claude, not heuristic string matching.

Each case receives 6 scores, each as `{"score": 0.0–1.0, "justification": "..."}`:

| Dimension | What it measures |
|-----------|-----------------|
| `answer_correctness` | Does the final answer address the query? |
| `citation_accuracy` | Are citations traceable to retrieved chunks? |
| `contradiction_resolution_quality` | Were contradictions explicitly resolved? |
| `tool_selection_efficiency` | Were only necessary tools invoked? |
| `context_budget_compliance` | Did agents stay within their token budgets? |
| `critique_agreement_rate` | Did Critique and Synthesis agree on flagged claims? |

**Test categories:**
- `baseline` — 5 standard queries
- `ambiguous` — 5 underspecified queries + long-context stress tests
- `adversarial` — 5 wrong-premise + 3 prompt injection + 2 contradictory retrieval cases

---

## Observability

Every SSE event, agent handoff, and tool call is stamped with:
- `job_id` — identifies the top-level request
- `trace_id` — OpenTelemetry distributed trace ID
- `span_id` — individual operation span
- `timestamp` — UTC ISO-8601
- `budget_remaining` — live token budget at event time

Structured JSON logs go to stdout (via `structlog`). In production, pipe to your log aggregator (Loki, Datadog, CloudWatch).

---

## Context Budget Management

Every agent declares a `max_context_budget`. The `ContextBudgetManager`:
- Tracks per-agent and shared token pools
- Compresses narrative agent outputs (losslessly preserves structured fields, citations, tool outputs)
- Logs `POLICY_VIOLATION` events when budgets are exceeded
- Never silently truncates — always raises `ContextBudgetExceeded` or emits a violation event

---

## Scaling Roadmap

1. **Horizontal workers** — the `SKIP LOCKED` queue already supports N workers; add replicas
2. **Dead-letter queue** — add a `dlq_steps` table for failed steps after max retries
3. **Real web search** — wire `WebSearchTool` to SerpAPI or Brave Search API
4. **Streaming embeddings** — replace batch sentence-transformers with a dedicated embedding service
5. **OpenTelemetry export** — add OTLP exporter to Jaeger/Tempo for UI trace viewing

---

## Known Limitations

- **WebSearch is fixture-backed** — no live internet access in this implementation
- **Embeddings require CPU warm-up** — first retrieval call loads `sentence-transformers` model (~1–2 seconds)
- **No persistent worker process** — the DAGExecutor runs in-process; for true horizontal scale, extract to a separate worker service
- **LLM fallbacks** — without `ANTHROPIC_API_KEY`, orchestration uses deterministic defaults; output quality will be limited
- **pgvector IVFFlat index** — requires `VACUUM` + re-index after bulk data changes; HNSW preferred for production at scale

## What This System Deliberately Does NOT Solve

- Real-time web crawling or knowledge base ingestion pipelines
- Multi-tenant job isolation (all jobs share a single DB)
- Model fine-tuning or RLHF
- Distributed tracing UI (OpenTelemetry export to Jaeger/Tempo is a roadmap item)

---

## Development

```bash
# Run all tests
pytest

# Syntax check
python -m compileall api app agents tools eval db tests

# Run security tests specifically
pytest tests/test_security.py -v

# Apply DB migrations
alembic upgrade head
```

AI-assisted engineering decisions documented in `COLLABORATIONS.md`.

---

## Architecture Decisions

See [`docs/architecture_critique.md`](docs/architecture_critique.md) for an honest architectural assessment, known tradeoffs, and design rationale.

See [`docs/implementation_plan.md`](docs/implementation_plan.md) for the full implementation plan covering all 10 spec sections.

