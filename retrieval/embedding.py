"""Embedding service using sentence-transformers."""

from typing import List, Union
import numpy as np
from sentence_transformers import SentenceTransformer


class EmbeddingService:
    """Service for generating text embeddings using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize the embedding service.

        Args:
            model_name: Name of the sentence-transformers model to use
        """
        self.model = SentenceTransformer(model_name)
        self.dimension = self.model.get_sentence_embedding_dimension()

    def encode(self, texts: Union[str, List[str]], batch_size: int = 32) -> np.ndarray:
        """
        Generate embeddings for text(s).

        Args:
            texts: Single text string or list of text strings
            batch_size: Batch size for processing

        Returns:
            Numpy array of embeddings
        """
        if isinstance(texts, str):
            texts = [texts]

        embeddings = self.model.encode(texts, batch_size=batch_size, show_progress_bar=False)
        return embeddings

    def encode_single(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            List of float values representing the embedding
        """
        embedding = self.encode(text)[0]
        return embedding.tolist()

    def similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """
        Calculate cosine similarity between two embeddings.

        Args:
            embedding1: First embedding
            embedding2: Second embedding

        Returns:
            Cosine similarity score
        """
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        return dot_product / (norm1 * norm2) if norm1 != 0 and norm2 != 0 else 0.0