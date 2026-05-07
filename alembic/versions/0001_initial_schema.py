"""Initial schema for agent orchestration platform

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-05-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

revision = '0001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'jobs',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('metadata', sa.JSON(), nullable=True),
    )

    op.create_table(
        'agent_events',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('job_id', pg.UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('input_hash', sa.String(length=128), nullable=True),
        sa.Column('output_hash', sa.String(length=128), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('token_count', sa.Integer(), nullable=True),
        sa.Column('policy_violations', sa.JSON(), nullable=True),
    )

    op.create_table(
        'tool_calls',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('job_id', pg.UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('tool_name', sa.String(length=128), nullable=False),
        sa.Column('attempt', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('input_payload', sa.JSON(), nullable=True),
        sa.Column('output_payload', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=64), nullable=False, server_default='started'),
        sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('reject_reason', sa.Text(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
    )

    op.create_table(
        'eval_runs',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=True),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('summary', sa.JSON(), nullable=True),
    )

    op.create_table(
        'eval_cases',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('eval_run_id', pg.UUID(as_uuid=True), sa.ForeignKey('eval_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('case_key', sa.String(length=128), nullable=False),
        sa.Column('input_payload', sa.JSON(), nullable=True),
        sa.Column('expected_payload', sa.JSON(), nullable=True),
        sa.Column('actual_payload', sa.JSON(), nullable=True),
        sa.Column('verdict', sa.String(length=64), nullable=True),
    )

    op.create_table(
        'eval_scores',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('eval_run_id', pg.UUID(as_uuid=True), sa.ForeignKey('eval_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('dimension', sa.String(length=128), nullable=False),
        sa.Column('score', sa.Numeric(5, 3), nullable=False),
        sa.Column('justification', sa.Text(), nullable=True),
    )

    op.create_table(
        'prompt_rewrites',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('original_prompt', sa.Text(), nullable=False),
        sa.Column('proposed_prompt', sa.Text(), nullable=False),
        sa.Column('dimension', sa.String(length=128), nullable=False),
        sa.Column('justification', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('metadata', sa.JSON(), nullable=True),
    )

    op.create_table(
        'rewrite_approvals',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('prompt_rewrite_id', pg.UUID(as_uuid=True), sa.ForeignKey('prompt_rewrites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('approved', sa.Boolean(), nullable=False),
        sa.Column('reviewer', sa.String(length=128), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('performance_delta', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table('rewrite_approvals')
    op.drop_table('prompt_rewrites')
    op.drop_table('eval_scores')
    op.drop_table('eval_cases')
    op.drop_table('eval_runs')
    op.drop_table('tool_calls')
    op.drop_table('agent_events')
    op.drop_table('jobs')
