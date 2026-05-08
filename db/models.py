import enum
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Index, Enum
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


def generate_uuid() -> str:
    return str(uuid.uuid4())


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class JobStepStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class EvaluationCategory(str, enum.Enum):
    baseline = "baseline"
    ambiguous = "ambiguous"
    adversarial = "adversarial"


class RewriteStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Decision(str, enum.Enum):
    approve = "approve"
    reject = "reject"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(JobStatus, name="job_status"), nullable=False, server_default=JobStatus.pending.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events = relationship("AgentEvent", back_populates="job", cascade="all, delete-orphan")
    tool_calls = relationship("ToolCall", back_populates="job", cascade="all, delete-orphan")
    steps = relationship("JobStep", back_populates="job", cascade="all, delete-orphan")


class JobStep(Base):
    __tablename__ = "job_steps"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    step_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(JobStepStatus, name="job_step_status"), nullable=False, server_default=JobStepStatus.pending.value
    )
    state_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    job = relationship("Job", back_populates="steps")


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_violation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job = relationship("Job", back_populates="events")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_num: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job = relationship("Job", back_populates="tool_calls")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    category_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dimension_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    test_case_results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    cases = relationship("EvalCase", back_populates="eval_run", cascade="all, delete-orphan")
    rewrites = relationship("PromptRewrite", back_populates="eval_run", cascade="all, delete-orphan")



class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(Enum(EvaluationCategory, name="eval_category"), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    eval_run = relationship("EvalRun", back_populates="cases")
    scores = relationship("EvalScore", back_populates="eval_case", cascade="all, delete-orphan")


class EvalScore(Base):
    __tablename__ = "eval_scores"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[str] = mapped_column(ForeignKey("eval_cases.id", ondelete="CASCADE"), nullable=False)
    dimension: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    eval_case = relationship("EvalCase", back_populates="scores")


class PromptRewrite(Base):
    __tablename__ = "prompt_rewrites"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    eval_run_id: Mapped[str | None] = mapped_column(ForeignKey("eval_runs.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dimension: Mapped[str] = mapped_column(String(128), nullable=False)
    original_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(RewriteStatus, name="rewrite_status"), nullable=False, server_default=RewriteStatus.pending.value
    )
    performance_delta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(256), nullable=True)

    approvals = relationship("RewriteApproval", back_populates="prompt_rewrite", cascade="all, delete-orphan")
    eval_run = relationship("EvalRun", back_populates="rewrites", foreign_keys=[eval_run_id])


class RewriteApproval(Base):
    __tablename__ = "rewrite_approvals"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rewrite_id: Mapped[str] = mapped_column(ForeignKey("prompt_rewrites.id", ondelete="CASCADE"), nullable=False)
    decision: Mapped[str] = mapped_column(Enum(Decision, name="rewrite_decision"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    delta_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    prompt_rewrite = relationship("PromptRewrite", back_populates="approvals")


# Retrieval System Models

class DocumentSource(str, enum.Enum):
    web = "web"
    file = "file"
    api = "api"
    manual = "manual"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Enum(DocumentSource, name="document_source"), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)  # sentence-transformers default dim
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index('ix_document_chunks_embedding', embedding, postgresql_using='ivfflat'),
    )


class RetrievalQuery(Base):
    __tablename__ = "retrieval_queries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    query_embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    results = relationship("RetrievalResult", back_populates="query", cascade="all, delete-orphan")


class RetrievalResult(Base):
    __tablename__ = "retrieval_results"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_id: Mapped[str] = mapped_column(ForeignKey("retrieval_queries.id", ondelete="CASCADE"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False)
    semantic_score: Mapped[float] = mapped_column(Float, nullable=False)
    bm25_score: Mapped[float] = mapped_column(Float, nullable=False)
    combined_score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    query = relationship("RetrievalQuery", back_populates="results")
    chunk = relationship("DocumentChunk")
