# Real-Time Multi-Agent LLM Orchestration and Evaluation System

Python/FastAPI system for real-time multi-agent orchestration, SSE tracing, PostgreSQL logging, deterministic evaluation, and auditable prompt rewrite proposals. 
The system is built as a production-ready, durable state machine (DAG), removing "fake agentic" loops in favor of deterministic orchestration where possible.

## One-Command Setup

```bash
cp .env.example .env && docker compose up
```

On Windows PowerShell:

```powershell
copy .env.example .env
docker compose up
```

Services:
- API: `http://localhost:8000`
- FastAPI docs: `http://localhost:8000/docs`
- Log UI: `http://localhost:8080`
- PostgreSQL: `localhost:5432`

Set `ANTHROPIC_API_KEY` in `.env` for live Claude calls.

## Architecture Highlights

1. **Durable Job Queue (PostgreSQL SKIP LOCKED)**:
   The orchestration pipeline has been refactored into a `DAGExecutor`. Instead of brittle in-memory async generators, the system relies on a PostgreSQL queue using `SKIP LOCKED`. This allows horizontally scalable worker consumption, fault tolerance, and restartability.

2. **Strict Sandboxing via Docker**:
   The `CodeSandboxTool` was rebuilt to use Docker container-level isolation using `docker-py` instead of naive `subprocess.run`.
   - `network_mode="none"`
   - `read_only=True` root filesystem
   - `mem_limit="128m"` and `pids_limit=10`

3. **Hybrid Retrieval (pgvector + tsvector)**:
   In-memory BM25 has been replaced. We use PostgreSQL `to_tsvector` keyword matching alongside `pgvector` semantic search, fused automatically via a Reciprocal Rank Fusion (RRF) CTE, protecting against SQL injection via strict parameterized inputs.

4. **LLM-As-A-Judge Evaluation**:
   The evaluation runner (`eval/runner.py`) uses an LLM (Anthropic) to score agent traces across 6 dimensions, replacing brittle regex/heuristic matching.

## Architecture Diagram

```text
Client
  | POST /query
  v
API (FastAPI) --> Saves Job + initial JobStep to PG
  |
  +--> GET /jobs/{job_id}/stream (SSE)
  |
  v
Worker / DAGExecutor (Reads from PG Queue)
  |
  +--> OrchestratorAgent (Plans DAG execution)
  +--> DecompositionAgent
  +--> RAGAgent -----> Tools: WebSearch, NLToSQL, CodeSandbox
  +--> CritiqueAgent
  +--> SynthesisAgent
  |
  v
PostgreSQL
  +--> jobs & job_steps (SKIP LOCKED queue)
  +--> document_chunks (pgvector & tsvector)
  +--> agent_events & tool_calls
```

## Known Limitations

- The WebSearch tool is fixture-backed, not connected to the public web.
- The evaluation loop proposes prompt rewrites, but a human must approve them via `/rewrites/{id}/decision`.

## Development

```bash
pytest
```
