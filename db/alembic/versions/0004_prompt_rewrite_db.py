"""Add prompt rewrite fields and eval run breakdown columns.

Revision ID: 0004_prompt_rewrite_db
Revises: 0003_add_job_step
Create Date: 2026-05-09

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_prompt_rewrite_db"
down_revision = "0003_add_job_step"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new JSONB columns to eval_runs
    op.add_column("eval_runs", sa.Column("category_breakdown", postgresql.JSONB(), nullable=True))
    op.add_column("eval_runs", sa.Column("dimension_scores", postgresql.JSONB(), nullable=True))
    op.add_column("eval_runs", sa.Column("test_case_results", postgresql.JSONB(), nullable=True))

    # Alter prompt_rewrites: rename run_id -> eval_run_id (nullable), add new columns
    # First add the new columns, then drop old constraint if column exists
    op.add_column("prompt_rewrites", sa.Column("performance_delta", postgresql.JSONB(), nullable=True))
    op.add_column("prompt_rewrites", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("prompt_rewrites", sa.Column("decided_by", sa.String(256), nullable=True))

    # Rename run_id -> eval_run_id with nullable change
    # Use raw SQL for column rename which may not be in older alembic
    op.execute("ALTER TABLE prompt_rewrites ADD COLUMN IF NOT EXISTS eval_run_id UUID REFERENCES eval_runs(id) ON DELETE SET NULL")
    # Copy data from run_id if it exists
    op.execute("UPDATE prompt_rewrites SET eval_run_id = run_id WHERE eval_run_id IS NULL")
    # Drop old run_id column if it exists
    try:
        op.drop_column("prompt_rewrites", "run_id")
    except Exception:
        pass  # Column might not exist in all environments


def downgrade() -> None:
    op.add_column("prompt_rewrites", sa.Column("run_id", sa.String(), nullable=True))
    op.execute("UPDATE prompt_rewrites SET run_id = eval_run_id::text WHERE run_id IS NULL")
    op.drop_column("prompt_rewrites", "eval_run_id")
    op.drop_column("prompt_rewrites", "decided_by")
    op.drop_column("prompt_rewrites", "approved_at")
    op.drop_column("prompt_rewrites", "performance_delta")
    op.drop_column("eval_runs", "test_case_results")
    op.drop_column("eval_runs", "dimension_scores")
    op.drop_column("eval_runs", "category_breakdown")
