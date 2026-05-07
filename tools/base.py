from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ToolResult:
    success: bool
    output: Dict[str, Any]
    error_code: str | None = None
    message: str | None = None


class BaseTool(ABC):
    tool_name: str

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name

    @abstractmethod
    def execute(self, input_data: Dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def on_timeout(self) -> ToolResult:
        return ToolResult(success=False, output={}, error_code="TIMEOUT", message="Tool timed out")

    def on_empty_result(self) -> ToolResult:
        return ToolResult(success=False, output={}, error_code="EMPTY_RESULT", message="No results returned")

    def on_malformed_input(self) -> ToolResult:
        return ToolResult(success=False, output={}, error_code="MALFORMED_INPUT", message="Malformed tool input")
