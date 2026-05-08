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
    job_status = pg.ENUM('pending', 'running', 'completed', 'failed', name='job_status', create_type=False)
    eval_category = pg.ENUM('baseline', 'ambiguous', 'adversarial', name='eval_category', create_type=False)
    rewrite_status = pg.ENUM('pending', 'approved', 'rejected', name='rewrite_status', create_type=False)
    rewrite_decision = pg.ENUM('approve', 'reject', name='rewrite_decision', create_type=False)

    job_status.create(op.get_bind(), checkfirst=True)
    eval_category.create(op.get_bind(), checkfirst=True)
    rewrite_status.create(op.get_bind(), checkfirst=True)
    rewrite_decision.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'jobs',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('status', job_status, nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'agent_events',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('job_id', pg.UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('input_hash', sa.String(length=128), nullable=True),
        sa.Column('output_hash', sa.String(length=128), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('token_count', sa.Integer(), nullable=True),
        sa.Column('policy_violation', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('payload', pg.JSONB(), nullable=True),
        sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'tool_calls',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('job_id', pg.UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('tool_name', sa.String(length=128), nullable=False),
        sa.Column('input', pg.JSONB(), nullable=True),
        sa.Column('output', pg.JSONB(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('retry_num', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('accepted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'eval_runs',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('total_cases', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('summary', pg.JSONB(), nullable=True),
    )

    op.create_table(
        'eval_cases',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('run_id', pg.UUID(as_uuid=True), sa.ForeignKey('eval_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('case_id', sa.String(length=128), nullable=False),
        sa.Column('category', eval_category, nullable=False),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('expected_answer', sa.Text(), nullable=True),
        sa.Column('actual_answer', sa.Text(), nullable=True),
        sa.Column('passed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )

    op.create_table(
        'eval_scores',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('case_id', pg.UUID(as_uuid=True), sa.ForeignKey('eval_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('dimension', sa.String(length=128), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('justification', sa.Text(), nullable=True),
    )

    op.create_table(
        'prompt_rewrites',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('run_id', pg.UUID(as_uuid=True), sa.ForeignKey('eval_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('dimension', sa.String(length=128), nullable=False),
        sa.Column('original_prompt', sa.Text(), nullable=False),
        sa.Column('proposed_prompt', sa.Text(), nullable=True),
        sa.Column('diff', sa.Text(), nullable=True),
        sa.Column('justification', sa.Text(), nullable=True),
        sa.Column('status', rewrite_status, nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'rewrite_approvals',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('rewrite_id', pg.UUID(as_uuid=True), sa.ForeignKey('prompt_rewrites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('decision', rewrite_decision, nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('delta_scores', pg.JSONB(), nullable=True),
    )


def downgrade():
    job_status = pg.ENUM('pending', 'running', 'completed', 'failed', name='job_status', create_type=False)
    eval_category = pg.ENUM('baseline', 'ambiguous', 'adversarial', name='eval_category', create_type=False)
    rewrite_status = pg.ENUM('pending', 'approved', 'rejected', name='rewrite_status', create_type=False)
    rewrite_decision = pg.ENUM('approve', 'reject', name='rewrite_decision', create_type=False)

    op.drop_table('rewrite_approvals')
    op.drop_table('prompt_rewrites')
    op.drop_table('eval_scores')
    op.drop_table('eval_cases')
    op.drop_table('eval_runs')
    op.drop_table('tool_calls')
    op.drop_table('agent_events')
    op.drop_table('jobs')
    rewrite_decision.drop(op.get_bind(), checkfirst=True)
    rewrite_status.drop(op.get_bind(), checkfirst=True)
    eval_category.drop(op.get_bind(), checkfirst=True)
    job_status.drop(op.get_bind(), checkfirst=True)
