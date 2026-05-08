"""Agent package for orchestration classes and prompt definitions."""

from agents.base import BaseAgent
from agents.manager import AgentManager
from agents.standard_agents import (
    OrchestratorAgent,
    DecompositionAgent,
    RAGAgent,
    CritiqueAgent,
    SynthesisAgent,
    RetrievalAgent,
    CompressionAgent,
    VerificationAgent,
    RefinementAgent,
    MetaAgent,
)

__all__ = [
    "BaseAgent",
    "AgentManager",
    "OrchestratorAgent",
    "DecompositionAgent",
    "RAGAgent",
    "CritiqueAgent",
    "SynthesisAgent",
    "RetrievalAgent",
    "CompressionAgent",
    "VerificationAgent",
    "RefinementAgent",
    "MetaAgent",
]
