"""Document ingestion service for processing and storing documents."""

from typing import Dict, Any, List, Optional
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from .chunking import TextChunker
from .embedding import EmbeddingService
from db.models import Document, DocumentChunk, DocumentSource


class DocumentIngestionService:
    """Service for ingesting documents into the retrieval system."""

    def __init__(
        self,
        chunker: TextChunker,
        embedding_service: EmbeddingService
    ):
        """
        Initialize the document ingestion service.

        Args:
            chunker: Text chunker instance
            embedding_service: Embedding service instance
        """
        self.chunker = chunker
        self.embedding_service = embedding_service

    async def ingest_document(
        self,
        content: str,
        source: DocumentSource,
        source_url: Optional[str] = None,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        db_session: AsyncSession = None
    ) -> str:
        """
        Ingest a document into the system.

        Args:
            content: Document content
            source: Source type (web, file, api, manual)
            source_url: Optional source URL
            title: Optional document title
            metadata: Optional metadata
            db_session: Database session

        Returns:
            Document ID
        """
        if db_session is None:
            raise ValueError("Database session required")

        # Create document record
        document_id = str(uuid4())
        document = Document(
            id=document_id,
            source=source,
            source_url=source_url,
            title=title,
            content=content,
            metadata=metadata or {}
        )
        db_session.add(document)

        # Chunk the document
        chunks_data = self.chunker.chunk_text(content, metadata)

        # Generate embeddings and create chunk records
        chunk_contents = [chunk["content"] for chunk in chunks_data]
        embeddings = self.embedding_service.encode(chunk_contents)

        for i, (chunk_data, embedding) in enumerate(zip(chunks_data, embeddings)):
            chunk = DocumentChunk(
                id=str(uuid4()),
                document_id=document_id,
                chunk_index=chunk_data["chunk_index"],
                content=chunk_data["content"],
                token_count=chunk_data["token_count"],
                embedding=embedding.tolist(),
                metadata=chunk_data["metadata"]
            )
            db_session.add(chunk)

        await db_session.commit()
        return document_id

    async def ingest_batch(
        self,
        documents: List[Dict[str, Any]],
        db_session: AsyncSession = None
    ) -> List[str]:
        """
        Ingest multiple documents in batch.

        Args:
            documents: List of document dictionaries with keys:
                content, source, source_url (optional), title (optional), metadata (optional)
            db_session: Database session

        Returns:
            List of document IDs
        """
        document_ids = []
        for doc_data in documents:
            doc_id = await self.ingest_document(
                content=doc_data["content"],
                source=doc_data["source"],
                source_url=doc_data.get("source_url"),
                title=doc_data.get("title"),
                metadata=doc_data.get("metadata"),
                db_session=db_session
            )
            document_ids.append(doc_id)
        return document_ids

    async def update_document(
        self,
        document_id: str,
        content: Optional[str] = None,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        db_session: AsyncSession = None
    ) -> None:
        """
        Update an existing document and re-chunk if content changed.

        Args:
            document_id: Document ID to update
            content: New content (if updating)
            title: New title (if updating)
            metadata: New metadata (if updating)
            db_session: Database session
        """
        if db_session is None:
            raise ValueError("Database session required")

        # Get existing document
        from sqlalchemy import select
        stmt = select(Document).where(Document.id == document_id)
        result = await db_session.execute(stmt)
        document = result.scalar_one_or_none()

        if not document:
            raise ValueError(f"Document {document_id} not found")

        # Update fields
        if title is not None:
            document.title = title
        if metadata is not None:
            document.metadata = metadata
        if content is not None:
            document.content = content
            document.updated_at = datetime.now(timezone.utc)

            # Delete existing chunks
            from sqlalchemy import delete
            await db_session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )

            # Re-chunk and create new chunks
            chunks_data = self.chunker.chunk_text(content, metadata)
            chunk_contents = [chunk["content"] for chunk in chunks_data]
            embeddings = self.embedding_service.encode(chunk_contents)

            for i, (chunk_data, embedding) in enumerate(zip(chunks_data, embeddings)):
                chunk = DocumentChunk(
                    id=str(uuid4()),
                    document_id=document_id,
                    chunk_index=chunk_data["chunk_index"],
                    content=chunk_data["content"],
                    token_count=chunk_data["token_count"],
                    embedding=embedding.tolist(),
                    metadata=chunk_data["metadata"]
                )
                db_session.add(chunk)

        await db_session.commit()