from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

from app.context import ToolOutput


@dataclass
class ToolResult:
    success: bool
    output: Dict[str, Any]
    error_code: str | None = None
    message: str | None = None


class BaseTool(ABC):
    """Base class for all tools in the orchestration system."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self.execution_count = 0
        self.total_latency_ms = 0

    @abstractmethod
    async def execute(self, input_data: Dict[str, Any]) -> ToolResult:
        """Execute the tool with given input and return a result."""
        raise NotImplementedError

    async def _execute_with_tracking(
        self, input_data: Dict[str, Any], job_id: str | None = None
    ) -> tuple[ToolResult, int]:
        """Execute tool with security inspection, latency tracking, and audit logging."""
        from tools.security import inspect_tool_input

        inspection = inspect_tool_input(self.tool_name, input_data, job_id=job_id)
        if not inspection.safe:
            return ToolResult(
                success=False,
                output={"violations": [v.__dict__ for v in inspection.violations]},
                error_code="SECURITY_VIOLATION",
                message=f"Input blocked by security policy: {inspection.violations[0].kind}",
            ), 0

        start_time = time.time()
        self.execution_count += 1

        try:
            result = await self.execute(input_data)
            latency_ms = int((time.time() - start_time) * 1000)
            self.total_latency_ms += latency_ms
            return result, latency_ms
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self.total_latency_ms += latency_ms
            return ToolResult(
                success=False,
                output={},
                error_code="EXECUTION_ERROR",
                message=str(e),
            ), latency_ms

    def to_tool_output(self, result: ToolResult, latency_ms: int, input_data: Dict[str, Any]) -> ToolOutput:
        """Convert ToolResult to ToolOutput for context."""
        return ToolOutput(
            tool_name=self.tool_name,
            input_payload=input_data,
            output_payload=result.output,
            latency_ms=latency_ms,
            success=result.success,
        )

    def on_timeout(self) -> ToolResult:
        return ToolResult(success=False, output={}, error_code="TIMEOUT", message="Tool timed out")

    def on_empty_result(self) -> ToolResult:
        return ToolResult(success=False, output={}, error_code="EMPTY_RESULT", message="No results returned")

    def on_malformed_input(self) -> ToolResult:
        return ToolResult(success=False, output={}, error_code="MALFORMED_INPUT", message="Malformed tool input")

    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics for this tool."""
        avg_latency = self.total_latency_ms / max(self.execution_count, 1)
        return {
            "tool_name": self.tool_name,
            "execution_count": self.execution_count,
            "total_latency_ms": self.total_latency_ms,
            "avg_latency_ms": avg_latency,
        }
