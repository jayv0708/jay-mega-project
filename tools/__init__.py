"""Tool package for agent-executable tools.

Lazy imports — do not eagerly load all tools at module level to avoid
dragging in heavy ML/Docker dependencies during unit test collection.
"""

from tools.base import BaseTool, ToolResult
from tools.security import (
    inspect_tool_input,
    inspect_retrieval_chunk,
    sanitize_text,
    SecurityViolation,
    InspectionResult,
)

__all__ = [
    "BaseTool",
    "ToolResult",
    "inspect_tool_input",
    "inspect_retrieval_chunk",
    "sanitize_text",
    "SecurityViolation",
    "InspectionResult",
]
