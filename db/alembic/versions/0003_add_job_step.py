"""Add JobStep state machine

Revision ID: 0003
Revises: 5d314e8221e5
Create Date: 2026-05-08 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, None] = '5d314e8221e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum type
    job_step_status = postgresql.ENUM('pending', 'running', 'completed', 'failed', name='job_step_status')
    job_step_status.create(op.get_bind(), checkfirst=True)

    op.create_table('job_steps',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('job_id', sa.UUID(), nullable=False),
        sa.Column('step_name', sa.String(length=128), nullable=False),
        sa.Column('status', job_step_status, server_default='pending', nullable=False),
        sa.Column('state_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('job_steps')
    job_step_status = postgresql.ENUM('pending', 'running', 'completed', 'failed', name='job_step_status')
    job_step_status.drop(op.get_bind(), checkfirst=True)
