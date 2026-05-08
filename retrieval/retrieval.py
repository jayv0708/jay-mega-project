"""Retrieval service with hybrid TSVector + pgvector search."""

from typing import List, Dict, Any, Tuple, Optional
import asyncio
from dataclasses import dataclass
from sqlalchemy import select, text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession

from .embedding import EmbeddingService
from db.models import DocumentChunk, RetrievalQuery, RetrievalResult


@dataclass
class RetrievedChunk:
    """Represents a retrieved document chunk with scores."""
    chunk_id: str
    content: str
    document_id: str
    chunk_index: int
    semantic_score: float
    bm25_score: float
    combined_score: float
    metadata: Dict[str, Any]


class RetrievalService:
    """Service for hybrid document retrieval using PostgreSQL text search and pgvector."""

    def __init__(self, embedding_service: EmbeddingService):
        self.embedding_service = embedding_service

    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        semantic_weight: float = 0.7,
        bm25_weight: float = 0.3,
        db_session: AsyncSession = None
    ) -> List[RetrievedChunk]:
        if db_session is None:
            raise ValueError("Database session required")

        # Generate query embedding
        query_embedding = self.embedding_service.encode_single(query)

        # Vector parameter format for pgvector
        vector_str = f"[{','.join(map(str, query_embedding))}]"

        # Hybrid search using CTEs and Reciprocal Rank Fusion (RRF)
        stmt = text("""
            WITH semantic_search AS (
                SELECT id,
                       1 - (embedding <=> :embedding_vector::vector) AS semantic_score,
                       RANK() OVER (ORDER BY embedding <=> :embedding_vector::vector) as semantic_rank
                FROM document_chunks
                ORDER BY semantic_rank
                LIMIT :limit_val
            ),
            keyword_search AS (
                SELECT id,
                       ts_rank(to_tsvector('english', content), websearch_to_tsquery('english', :search_query)) AS keyword_score,
                       RANK() OVER (ORDER BY ts_rank(to_tsvector('english', content), websearch_to_tsquery('english', :search_query)) DESC) as keyword_rank
                FROM document_chunks
                WHERE to_tsvector('english', content) @@ websearch_to_tsquery('english', :search_query)
                ORDER BY keyword_rank
                LIMIT :limit_val
            ),
            combined_search AS (
                SELECT COALESCE(s.id, k.id) as chunk_id,
                       COALESCE(s.semantic_score, 0.0) as semantic_score,
                       COALESCE(k.keyword_score, 0.0) as keyword_score,
                       (COALESCE(1.0 / (60 + s.semantic_rank), 0.0) * :semantic_weight) +
                       (COALESCE(1.0 / (60 + k.keyword_rank), 0.0) * :keyword_weight) as rrf_score
                FROM semantic_search s
                FULL OUTER JOIN keyword_search k ON s.id = k.id
            )
            SELECT d.id, d.document_id, d.chunk_index, d.content, d.metadata_,
                   c.semantic_score, c.keyword_score, c.rrf_score
            FROM combined_search c
            JOIN document_chunks d ON d.id = c.chunk_id
            ORDER BY c.rrf_score DESC
            LIMIT :final_limit
        """).bindparams(
            bindparam('embedding_vector', vector_str),
            bindparam('search_query', query),
            bindparam('limit_val', top_k * 2),
            bindparam('final_limit', top_k),
            bindparam('semantic_weight', semantic_weight),
            bindparam('keyword_weight', bm25_weight)
        )

        result = await db_session.execute(stmt)
        rows = result.fetchall()
        
        results = []
        for row in rows:
            chunk = RetrievedChunk(
                chunk_id=str(row[0]),
                document_id=str(row[1]),
                chunk_index=row[2],
                content=row[3],
                metadata=row[4] or {},
                semantic_score=float(row[5]),
                bm25_score=float(row[6]),
                combined_score=float(row[7])
            )
            results.append(chunk)

        await self._save_retrieval_results(query, query_embedding, results, db_session)
        return results

    async def _save_retrieval_results(
        self,
        query: str,
        query_embedding: List[float],
        results: List[RetrievedChunk],
        db_session: AsyncSession
    ) -> None:
        retrieval_query = RetrievalQuery(
            query=query,
            query_embedding=query_embedding,
            top_k=len(results)
        )
        db_session.add(retrieval_query)
        await db_session.flush()

        for rank, result in enumerate(results, 1):
            retrieval_result = RetrievalResult(
                query_id=retrieval_query.id,
                chunk_id=result.chunk_id,
                semantic_score=result.semantic_score,
                bm25_score=result.bm25_score,
                combined_score=result.combined_score,
                rank=rank
            )
            db_session.add(retrieval_result)

        await db_session.commit()