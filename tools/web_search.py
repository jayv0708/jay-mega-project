from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any, Dict

from tools.base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    def __init__(self, fixture_path: Path) -> None:
        super().__init__("WebSearchTool")
        self.fixture_path = fixture_path

    def execute(self, input_data: Dict[str, Any]) -> ToolResult:
        start = perf_counter()
        if not isinstance(input_data, dict) or "query" not in input_data:
            return self.on_malformed_input()
        try:
            raw = self.fixture_path.read_text(encoding="utf-8")
            results = json.loads(raw).get("results", [])
            latency_ms = int((perf_counter() - start) * 1000)
            output = {"results": results, "latency_ms": latency_ms}
            if not results:
                return self.on_empty_result()
            return ToolResult(success=True, output=output)
        except Exception as exc:
            return ToolResult(success=False, output={}, error_code="SEARCH_ERROR", message=str(exc))
