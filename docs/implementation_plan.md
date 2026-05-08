# Production Upgrade for Multi-Agent LLM Orchestration System

This document outlines the architectural upgrade to transition the current multi-agent system from a partially-mocked, naive implementation into a robust, rigorous, evaluation-driven production platform.

## User Review Required

> [!WARNING]
> **Breaking Changes to State Management:** Moving from an asynchronous generator `yield` loop to a persistent, queue-driven State Machine (DAG). This means the `/query` endpoint will return a Job ID, and the SSE stream will attach to a queue listener instead of driving execution directly.
> 
> **Removal of Decorative Agents:** Agents like `CompressionAgent`, `MetaAgent`, `VerificationAgent`, and `RefinementAgent` which lack strong independent functional bounds will be removed or collapsed into standard functions/prompts.

## Open Questions

> [!IMPORTANT]
> 1. **Code Sandboxing Infrastructure:** The plan proposes using an isolated Docker container strategy for Python execution. Do you have access to a Docker daemon during execution, or should we use an isolated WASM runtime (like Pyodide) to minimize infrastructure requirements?
> 2. **Queueing Backbone:** The current plan proposes using PostgreSQL `SKIP LOCKED` rows for the job queue to avoid adding Redis. Is this acceptable to minimize infrastructure overhead?
> 3. **Observability Stack:** Should we include a basic local Jaeger container in `docker-compose.yml` for OpenTelemetry trace visualization?

---

## 1. Architecture Critique

*   **Fake Agenticity & Hardcoded Routing:** The `OrchestratorAgent` and `DecompositionAgent` rely on default fallbacks and hardcoded execution sequences (`["decomposition", "rag", "critique", "synthesis"]`). True dynamic DAG construction based on user intent is missing.
*   **Retrieval is Unscalable & Insecure:** The `RetrievalService` fetches **all** document chunks into memory to perform BM25 on every query. The pgvector search relies on dangerous string concatenation (`vector_literal`) instead of parameterized queries. Provenance mapping is faked.
*   **Security Vulnerabilities:** `CodeSandboxTool` uses `subprocess.run` with simple string exclusions for security. This is trivially bypassable.
*   **Fragile State & Missing Queueing:** The pipeline runs inside a single async request context (`OrchestrationPipeline.stream`). If the API node crashes, the job state is lost. There is no retry policy, DLQ, or checkpointing.
*   **Shallow Evaluation:** `eval/runner.py` uses heuristic word-matching instead of genuine LLM-based evaluation or robust retrieval metrics (Recall@K).

---

## 2. Prioritized Remediation Roadmap

1.  **Phase 1: Foundation (Days 1-2)**
    *   Implement durable job queue and step-level checkpointing using PostgreSQL.
    *   Sandbox hardening: Secure `CodeSandboxTool` via Docker or WASM.
2.  **Phase 2: Data & Retrieval (Days 3-4)**
    *   Re-engineer `RetrievalService` with parameterized pgvector queries.
    *   Implement scalable BM25 (using specialized Postgres extensions or pre-tokenized indices) and proper ingestion/chunking pipelines.
3.  **Phase 3: Core Orchestration (Days 5-6)**
    *   Collapse decorative agents.
    *   Build the dynamic routing planner with explicit heuristics.
4.  **Phase 4: Evaluation & Observability (Days 7-8)**
    *   Instrument code with OpenTelemetry.
    *   Write the LLM-as-a-Judge evaluation framework and regression testing loop.

---

## 3. Refactored Architecture

We will implement a **Deterministic Orchestration DAG** paradigm.

*   **API Node**: FastAPI. Accepts requests, writes `Job` to Postgres, returns `job_id`. Exposes an SSE endpoint that subscribes to job events.
*   **Worker Node**: Pulls jobs from the Postgres queue. Executes the DAG state machine.
*   **State Machine (DAG)**:
    1.  `Planner`: Analyzes query -> Emits explicit steps (e.g., `FetchData`, `RunCode`, `Synthesize`).
    2.  `Executor`: Runs tools/agents idempotently. Saves state per node.
*   **Retrieval Stack**: PostgreSQL `pgvector` for dense retrieval, native `tsvector` for lexical retrieval (BM25-equivalent) to avoid memory crashes.
*   **Evaluation Engine**: Offline runner utilizing LLM judges for groundedness, MRR, and exact-match checks.

---

## 4. Folder Structure (Target)

```text
/api                # FastAPI endpoints, SSE streaming layer
/app
  /dag              # Explicit DAG state machine logic (replacing pipeline.py)
  /heuristics       # Routing heuristics and planners
/agents             # Bounded functional agents (Planner, Synthesizer, Critique)
/core
  /telemetry        # OpenTelemetry tracing and token accounting
  /security         # Tool sanitization, Docker/WASM sandboxing
/db
  /migrations       # Alembic
  /models.py        # SQLAlchemy models (updated schema)
/eval
  /judges           # LLM-as-a-judge implementations
  /metrics          # Recall@K, Grounding, MRR
/queue              # Durable PG-backed job queue, DLQ, and worker logic
/retrieval
  /ingest           # Chunking, metadata extraction
  /search           # Hybrid search (pgvector + tsvector)
/tools              # Typed inputs/outputs, Secure Sandbox
docker-compose.yml
```

---

## 5. Simplification Recommendations

*   **[DELETE] `CompressionAgent`, `MetaAgent`, `VerificationAgent`, `RefinementAgent`**: These are decorative and provide no structural value that a well-written prompt in the Synthesis agent cannot provide.
*   **[REPLACE] Mocked `RAGAgent`**: Convert `RAGAgent` to a standard Tool `SearchKnowledgeBase`. Agents should call tools, not *be* the tool.
*   **[COLLAPSE] Evaluation**: Remove regex-based scoring in `eval/runner.py`. Use a single `Judge` LLM prompt to compute boolean correctness and grounding.

---

## 6. Proposed Code & Implementation Details

### A. Database Schemas (Durable Execution)

```python
#### [MODIFY] db/models.py
class JobStep(Base):
    __tablename__ = "job_steps"
    
    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    step_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(64)) # PENDING, RUNNING, COMPLETED, FAILED
    state_snapshot: Mapped[dict] = mapped_column(JSONB)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_reason: Mapped[str] = mapped_column(Text, nullable=True)
```

### B. Queue Implementation
Instead of an external Redis broker, we will use Postgres `SKIP LOCKED` to keep infrastructure simple.
*   **Worker**: Polls `jobs` where `status='pending'` using `SELECT ... FOR UPDATE SKIP LOCKED`.
*   **DLQ**: Jobs failing > 3 times move to `status='failed'` and are logged for manual replay.

### C. Retrieval Implementation (Production-Grade)
*   **Lexical**: Drop `rank_bm25` (memory bound). Use PostgreSQL `to_tsvector` and `ts_rank` for lexical search.
*   **Semantic**: Fix SQL injection by using SQLAlchemy parameters.
*   **Reranking**: Use Reciprocal Rank Fusion (RRF) to combine `ts_rank` and vector similarity.

### D. Security Hardening Plan
*   **Code Sandbox**: Replace `subprocess.run` with the Docker API. Mount a read-only filesystem. Drop all network capabilities (`--network none`). Set strict CPU/Memory quotas via cgroups.
*   **Prompt Injection**: Implement a system prompt guardrail that checks inputs against known injection heuristics before routing.

### E. Observability Implementation
*   Inject `opentelemetry-sdk`.
*   Create a `@traced_agent` and `@traced_tool` decorator that automatically extracts `span_id`, calculates latency, tracks token usage via `litellm` or custom callbacks, and dumps a structured JSON log.

### F. Evaluation Upgrades
*   **Judges**: Implement a separate LLM call in `eval/runner.py` using a strict output schema to grade `citation_grounding_accuracy` and `unsupported_claims`.
*   **Metrics**: Implement `MRR` and `Recall@K` scripts for evaluating the `/retrieval` endpoints independently of the agents.

---

## Verification Plan

### Automated Tests
*   `pytest tests/` covering sandbox escape attempts, SQL injection payloads on retrieval, and dead-letter queue behavior.
*   Run the expanded evaluation dataset and ensure zero regressions on baseline assertions.

### Manual Verification
*   Run `docker-compose up` to verify the system starts from scratch.
*   Submit a query via the API and ensure the SSE stream correctly relays state transitions from the Postgres queue.
*   Submit a malicious Python code execution query to verify the sandbox blocks network and file IO.
