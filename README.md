# Real-Time Multi-Agent LLM Orchestration and Evaluation System

Python/FastAPI system for real-time multi-agent orchestration, SSE tracing, PostgreSQL logging, deterministic evaluation, and auditable prompt rewrite proposals. The implementation avoids LangChain and LlamaIndex; orchestration, tools, evals, and prompt loops are local Python code.

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

Set `ANTHROPIC_API_KEY` in `.env` for live Claude calls. Without it, the system uses deterministic fallbacks so local setup and tests still run.

## Architecture

```text
Client
  |
  | POST /query (SSE)
  v
API (FastAPI)
  |
  | creates job + streams events
  v
Worker / Pipeline
  |
  v
OrchestratorAgent
  |
  +--> DecompositionAgent
  +--> RAGAgent -----> Tools: WebSearch, NLToSQL, CodeSandbox, SelfReflection
  +--> CritiqueAgent
  +--> SynthesisAgent
  +--> CompressionAgent when context budget is tight
  |
  v
PostgreSQL
  |
  +--> jobs
  +--> agent_events
  +--> tool_calls
  +--> eval_runs / eval_cases / eval_scores
  +--> prompt_rewrites / rewrite_approvals
```

## API

The application exposes exactly five main endpoints:

- `POST /query`: accepts `{query: str}` and streams JSON SSE events.
- `GET /jobs/{job_id}/trace`: reconstructs agent/tool execution trace.
- `GET /evals/latest`: returns latest eval summary by category and dimension.
- `POST /rewrites/{rewrite_id}/decision`: approves or rejects a pending prompt rewrite.
- `POST /evals/rerun-failures`: reruns only latest failed eval cases.

Error responses use:

```json
{"error_code": "CODE", "message": "text", "job_id": null, "timestamp": "ISO8601"}
```

## Agents

`OrchestratorAgent`
- Input: `SharedContext.query`
- Output: routing decision JSON in `agent_outputs` and `metadata.routing_decision`
- Boundary: chooses agent order and budgets through a structured Anthropic call or deterministic fallback; it does not execute tools or synthesize final answers.

`DecompositionAgent`
- Input: user query and current context
- Output: typed subtask DAG with dependencies
- Boundary: resolves underspecified inputs internally and never asks the user clarifying questions.

`RAGAgent`
- Input: query and subtasks
- Output: at least two retrieved chunks, cited sentences, and a multi-hop synthesis fragment
- Boundary: every emitted sentence must map to chunk provenance.

`CritiqueAgent`
- Input: other agents' outputs
- Output: span-level claim scores with confidence, flags, and reasons
- Boundary: critiques through `SharedContext` only; it never calls another agent directly.

`SynthesisAgent`
- Input: subtasks, citations, critique flags, contradictions
- Output: final answer and `provenance_map`
- Boundary: resolves contradictions explicitly before finalizing.

`CompressionAgent`
- Input: full shared context
- Output: compressed context plus audit metadata
- Boundary: preserves structured data exactly and only summarizes free-text narrative filler.

`MetaAgent`
- Input: failed eval cases and prompt files
- Output: pending prompt rewrite with unified diff
- Boundary: proposes candidates only; it does not permanently apply prompts without approval and positive targeted rerun results.

## Evaluation

Run all eval fixtures:

```bash
pytest eval/
```

The eval harness includes 15 cases:
- 5 baseline
- 5 ambiguous
- 5 adversarial

Each case receives six scores:
- `answer_correctness`
- `citation_accuracy`
- `contradiction_resolution_quality`
- `tool_selection_efficiency`
- `context_budget_compliance`
- `critique_agreement_rate`

No third-party eval framework is used.

## Known Limitations

- The default local mode uses deterministic fallbacks when `ANTHROPIC_API_KEY` is absent, so it demonstrates orchestration behavior but is not a substitute for live model quality.
- The WebSearch tool is fixture-backed, not connected to the public web.
- The code sandbox uses subprocess isolation plus static policy checks; it is suitable for tests, not hostile multi-tenant execution.
- Very long queries can still exceed practical memory/time limits. The budget manager compresses narrative context and records violations, but it does not implement a full semantic memory hierarchy.
- The self-improving loop proposes and tests candidate prompts, but it does not learn across runs, train models, or silently auto-apply changes.
- The local JSON rewrite store is used as a testable fallback; production deployments should persist prompt rewrites and approvals fully in PostgreSQL.

## Roadmap

- Add a durable PostgreSQL-backed job queue for the worker service.
- Persist all eval and rewrite fallback JSON state into database tables in normal runtime.
- Add real retrieval backends behind the RAG tool boundary.
- Harden CodeSandbox with container-level isolation.
- Add Alembic startup migration automation to the Compose workflow.
- Build a richer log UI with filtering by job, agent, event type, and policy violation.
- Add OpenTelemetry traces and structured JSON application logs.

## Development

```bash
pytest
python -m compileall api app agents tools eval db tests
```

AI-assisted engineering decisions are documented in `COLLABORATIONS.md`.
