"""Text chunking utilities for document processing."""

import re
from typing import List, Dict, Any
import tiktoken


class TextChunker:
    """Handles text chunking with token-aware splitting."""

    def __init__(self, chunk_size: int = 512, overlap: int = 50, encoding_name: str = "cl100k_base"):
        """
        Initialize the text chunker.

        Args:
            chunk_size: Maximum tokens per chunk
            overlap: Number of tokens to overlap between chunks
            encoding_name: Tiktoken encoding to use
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.encoding = tiktoken.get_encoding(encoding_name)

    def chunk_text(self, text: str, metadata: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Split text into chunks with token limits.

        Args:
            text: Text to chunk
            metadata: Optional metadata to include with each chunk

        Returns:
            List of chunk dictionaries with content, token_count, and metadata
        """
        if metadata is None:
            metadata = {}

        # Split text into sentences for better semantic boundaries
        sentences = self._split_into_sentences(text)

        chunks = []
        current_chunk = ""
        current_tokens = 0
        chunk_index = 0

        for sentence in sentences:
            sentence_tokens = len(self.encoding.encode(sentence))

            # If adding this sentence would exceed chunk size
            if current_tokens + sentence_tokens > self.chunk_size and current_chunk:
                # Save current chunk
                chunks.append({
                    "content": current_chunk.strip(),
                    "token_count": current_tokens,
                    "chunk_index": chunk_index,
                    "metadata": metadata.copy()
                })
                chunk_index += 1

                # Start new chunk with overlap from previous chunk
                if self.overlap > 0 and current_tokens > self.overlap:
                    overlap_text = self._get_overlap_text(current_chunk, self.overlap)
                    current_chunk = overlap_text + sentence
                    current_tokens = len(self.encoding.encode(current_chunk))
                else:
                    current_chunk = sentence
                    current_tokens = sentence_tokens
            else:
                current_chunk += sentence
                current_tokens += sentence_tokens

        # Add final chunk
        if current_chunk.strip():
            chunks.append({
                "content": current_chunk.strip(),
                "token_count": current_tokens,
                "chunk_index": chunk_index,
                "metadata": metadata.copy()
            })

        return chunks

    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences using regex."""
        # Simple sentence splitting - can be enhanced with NLP libraries
        sentence_endings = r'(?<=[.!?])\s+'
        sentences = re.split(sentence_endings, text.strip())

        # Filter out empty sentences
        return [s.strip() for s in sentences if s.strip()]

    def _get_overlap_text(self, text: str, overlap_tokens: int) -> str:
        """Extract overlap text from the end of a chunk."""
        tokens = self.encoding.encode(text)
        if len(tokens) <= overlap_tokens:
            return text

        overlap_tokens_list = tokens[-overlap_tokens:]
        return self.encoding.decode(overlap_tokens_list)