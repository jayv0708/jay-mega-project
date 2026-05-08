#!/usr/bin/env python3
"""Script to populate test data for the retrieval system."""

import asyncio
from retrieval import DocumentIngestionService, EmbeddingService, TextChunker
from db.db import get_async_session
from db.models import DocumentSource


async def populate_test_data():
    """Populate the database with test documents for retrieval."""

    # Initialize services
    embedding_service = EmbeddingService()
    chunker = TextChunker()
    ingestion_service = DocumentIngestionService(chunker, embedding_service)

    # Test documents
    documents = [
        {
            "content": """
            Python is a high-level programming language known for its simplicity and readability.
            It was created by Guido van Rossum and first released in 1991. Python supports multiple
            programming paradigms, including procedural, object-oriented, and functional programming.
            It has a large standard library and a vast ecosystem of third-party packages.
            """,
            "source": DocumentSource.manual,
            "title": "Introduction to Python",
            "metadata": {"category": "programming", "language": "en"}
        },
        {
            "content": """
            Machine learning is a subset of artificial intelligence that focuses on algorithms
            that can learn from data without being explicitly programmed. It involves training
            models on data to make predictions or decisions. Common techniques include supervised
            learning, unsupervised learning, and reinforcement learning. Python is widely used
            for machine learning due to libraries like scikit-learn, TensorFlow, and PyTorch.
            """,
            "source": DocumentSource.manual,
            "title": "Machine Learning Overview",
            "metadata": {"category": "ai", "language": "en"}
        },
        {
            "content": """
            Web development involves creating websites and web applications. It typically includes
            frontend development (user interface) and backend development (server-side logic).
            Popular frontend technologies include HTML, CSS, and JavaScript with frameworks like
            React, Angular, and Vue.js. Backend technologies include Python with Django or Flask,
            Node.js, and various databases like PostgreSQL and MongoDB.
            """,
            "source": DocumentSource.manual,
            "title": "Web Development Guide",
            "metadata": {"category": "web", "language": "en"}
        },
        {
            "content": """
            Data science combines statistics, programming, and domain expertise to extract insights
            from data. It involves data collection, cleaning, analysis, and visualization.
            Python is the most popular language for data science, with libraries like pandas for
            data manipulation, NumPy for numerical computing, and matplotlib/seaborn for visualization.
            Jupyter notebooks are commonly used for exploratory data analysis.
            """,
            "source": DocumentSource.manual,
            "title": "Data Science Fundamentals",
            "metadata": {"category": "data", "language": "en"}
        }
    ]

    async with get_async_session() as db_session:
        document_ids = await ingestion_service.ingest_batch(documents, db_session)

        print(f"Successfully ingested {len(document_ids)} documents:")
        for i, doc_id in enumerate(document_ids, 1):
            print(f"  {i}. {doc_id}")

        # Commit the transaction
        await db_session.commit()

    print("Test data population complete!")


if __name__ == "__main__":
    asyncio.run(populate_test_data())