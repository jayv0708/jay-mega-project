from __future__ import annotations

from typing import Any, Dict, List

from tools.base import BaseTool, ToolResult


class SelfReflectionTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("SelfReflectionTool")

    def execute(self, input_data: Dict[str, Any]) -> ToolResult:
        if not isinstance(input_data, dict) or "agent_outputs" not in input_data:
            return self.on_malformed_input()

        outputs = input_data["agent_outputs"]
        contradictions: List[Dict[str, Any]] = []
        claims: List[str] = []

        for agent_id, agent_output in outputs.items():
            text = agent_output.get("output", "")
            if not isinstance(text, str):
                continue
            claims.append(text)

        if len(claims) > 1:
            contradictions.append({
                "span_a": claims[0],
                "span_b": claims[-1],
                "description": "Multiple agents produced potentially inconsistent answer fragments.",
            })

        return ToolResult(
            success=True,
            output={
                "contradictions": contradictions,
                "consistent_claims": claims,
            },
        )
