"""Agent package for orchestration classes and prompt definitions."""

from agents.base import BaseAgent
from agents.llm import AnthropicClient
from agents.standard_agents import (
    CritiqueAgent,
    DecompositionAgent,
    OrchestratorAgent,
    RAGAgent,
    SynthesisAgent,
    CompressionAgent,
)

__all__ = [
    "BaseAgent",
    "AnthropicClient",
    "OrchestratorAgent",
    "DecompositionAgent",
    "RAGAgent",
    "CritiqueAgent",
    "SynthesisAgent",
    "CompressionAgent",
]
