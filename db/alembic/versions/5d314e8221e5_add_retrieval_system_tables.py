"""Add retrieval system tables
Revision ID: 5d314e8221e5
Revises: 0001_initial_schema
Create Date: 2026-05-08 15:25:03.131326
"""
from alembic import op
import sqlalchemy as sa

revision = '5d314e8221e5'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None


"""Add retrieval system tables

Revision ID: 5d314e8221e5
Revises: 0001_initial_schema
Create Date: 2026-05-08 15:25:03.131326
"""
from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

revision = '5d314e8221e5'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None


def upgrade():
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create document_source enum
    document_source = pg.ENUM('web', 'file', 'api', 'manual', name='document_source', create_type=False)
    document_source.create(op.get_bind(), checkfirst=True)

    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('source', document_source, nullable=False),
        sa.Column('source_url', sa.String(length=2048), nullable=True),
        sa.Column('title', sa.String(length=512), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata', pg.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Create document_chunks table
    op.create_table(
        'document_chunks',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('document_id', pg.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False),
        sa.Column('embedding', sa.Column(sa.dialects.postgresql.VECTOR(384)), nullable=False),
        sa.Column('metadata', pg.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Create retrieval_queries table
    op.create_table(
        'retrieval_queries',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('query_embedding', sa.Column(sa.dialects.postgresql.VECTOR(384)), nullable=False),
        sa.Column('top_k', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Create retrieval_results table
    op.create_table(
        'retrieval_results',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('query_id', pg.UUID(as_uuid=True), sa.ForeignKey('retrieval_queries.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_id', pg.UUID(as_uuid=True), sa.ForeignKey('document_chunks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('semantic_score', sa.Float(), nullable=False),
        sa.Column('bm25_score', sa.Float(), nullable=False),
        sa.Column('combined_score', sa.Float(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
    )

    # Create indexes
    op.create_index('ix_document_chunks_embedding', 'document_chunks', ['embedding'], postgresql_using='ivfflat')
    op.create_index('ix_document_chunks_document_id', 'document_chunks', ['document_id'])
    op.create_index('ix_retrieval_results_query_id', 'retrieval_results', ['query_id'])
    op.create_index('ix_retrieval_results_chunk_id', 'retrieval_results', ['chunk_id'])


def downgrade():
    op.drop_index('ix_retrieval_results_chunk_id')
    op.drop_index('ix_retrieval_results_query_id')
    op.drop_index('ix_document_chunks_document_id')
    op.drop_index('ix_document_chunks_embedding')

    op.drop_table('retrieval_results')
    op.drop_table('retrieval_queries')
    op.drop_table('document_chunks')
    op.drop_table('documents')

    # Drop enum
    document_source = pg.ENUM('web', 'file', 'api', 'manual', name='document_source', create_type=False)
    document_source.drop(op.get_bind(), checkfirst=True)

    # Note: We don't drop the vector extension as it might be used by other parts of the system
