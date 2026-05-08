"""Tool orchestration with per-retry structured logging and SSE events."""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional

from app.context import SharedContext
from tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MAX_RETRIES = 2  # attempts 0, 1, 2 → up to 3 total


class ToolOrchestrator:
    """Manages tool execution with per-retry structured logging and SSE event emission."""

    def __init__(self, sse_emitter: Callable[..., Coroutine] | None = None) -> None:
        self.tools: Dict[str, BaseTool] = {}
        self.tool_call_log: List[Dict] = []
        # Optional coroutine: async def emit(event_type, agent_id, data) -> None
        self._sse_emitter = sse_emitter

    def register_tool(self, tool: BaseTool) -> None:
        self.tools[tool.tool_name] = tool
        logger.debug(f"Registered tool '{tool.tool_name}'")

    def unregister_tool(self, tool_name: str) -> None:
        if tool_name in self.tools:
            del self.tools[tool_name]

    async def execute_tool(self, tool_name: str, input_data: Dict) -> ToolResult:
        if tool_name not in self.tools:
            return ToolResult(success=False, output={}, error_code="TOOL_NOT_FOUND",
                              message=f"Tool '{tool_name}' not registered")
        try:
            result, _ = await self._execute_registered_tool(tool_name, input_data)
            return result
        except Exception as e:
            return ToolResult(success=False, output={}, error_code="EXECUTION_ERROR", message=str(e))

    async def execute_tool_with_retries(
        self,
        tool_name: str,
        input_data: Dict,
        *,
        agent_id: str,
        job_id: str,
        context: Optional[SharedContext] = None,
    ) -> ToolResult:
        """Execute a tool with up to MAX_RETRIES retries, logging each attempt individually."""
        current_input = dict(input_data)
        last_result: ToolResult | None = None

        for attempt in range(MAX_RETRIES + 1):  # 0, 1, 2
            result, latency_ms = await self._execute_once_for_log(tool_name, current_input)
            accepted = result.success

            self._log_tool_call(
                job_id=job_id,
                agent_id=agent_id,
                tool_name=tool_name,
                input_data=current_input,
                result=result,
                latency_ms=latency_ms,
                retry_num=attempt,
                accepted=accepted,
            )

            if context is not None:
                tool = self.tools.get(tool_name)
                if tool:
                    context.add_tool_output(tool.to_tool_output(result, latency_ms, current_input))

            if accepted:
                return result

            # Determine failure reason
            reason = _classify_failure(result)

            if attempt < MAX_RETRIES:
                # Emit TOOL_RETRY SSE event
                await self._emit_sse(
                    event_type="TOOL_RETRY",
                    agent_id=agent_id,
                    job_id=job_id,
                    data={
                        "tool_name": tool_name,
                        "attempt": attempt + 1,
                        "reason": reason,
                        "modified_input": current_input,
                        "previous_error_code": result.error_code,
                    },
                )
                current_input = self._modify_input_for_retry(current_input, result, attempt)
            else:
                # Final failure after all retries exhausted
                await self._emit_sse(
                    event_type="TOOL_FAILURE",
                    agent_id=agent_id,
                    job_id=job_id,
                    data={
                        "tool_name": tool_name,
                        "total_attempts": attempt + 1,
                        "final_error_code": result.error_code,
                        "reason": reason,
                    },
                )

            last_result = result

        return last_result or ToolResult(success=False, output={}, error_code="NO_ATTEMPT",
                                         message="Tool was not attempted")

    async def _emit_sse(self, event_type: str, agent_id: str, job_id: str, data: Dict) -> None:
        """Emit a structured SSE event via the injected emitter (if configured)."""
        structured = {
            "event_type": event_type,
            "agent_id": agent_id,
            "job_id": job_id,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("tool_event", extra=structured)
        if self._sse_emitter is not None:
            try:
                await self._sse_emitter(event_type=event_type, agent_id=agent_id, data=data)
            except Exception as exc:
                logger.warning(f"SSE emitter failed: {exc}")

    async def _execute_registered_tool(self, tool_name: str, input_data: Dict) -> tuple[ToolResult, int]:
        tool = self.tools[tool_name]
        result, latency_ms = await tool._execute_with_tracking(input_data)
        return result, latency_ms

    async def _execute_once_for_log(self, tool_name: str, input_data: Dict) -> tuple[ToolResult, int]:
        if tool_name not in self.tools:
            return (
                ToolResult(success=False, output={}, error_code="TOOL_NOT_FOUND",
                           message=f"Tool '{tool_name}' not registered"),
                0,
            )
        try:
            return await self._execute_registered_tool(tool_name, input_data)
        except Exception as exc:
            return ToolResult(success=False, output={}, error_code="EXECUTION_ERROR", message=str(exc)), 0

    def _modify_input_for_retry(self, input_data: Dict, result: ToolResult, retry_num: int) -> Dict:
        next_input = dict(input_data)
        next_input["retry_hint"] = {
            "retry_num": retry_num + 1,
            "previous_error_code": result.error_code,
            "previous_message": result.message,
        }
        if "query" in next_input:
            # On retry, broaden the query slightly
            q = str(next_input["query"]).strip()
            if retry_num == 0:
                next_input["query"] = q + " overview"
            elif retry_num == 1:
                next_input["query"] = q.split()[0] if q.split() else q
        return next_input

    def _log_tool_call(
        self,
        *,
        job_id: str,
        agent_id: str,
        tool_name: str,
        input_data: Dict,
        result: ToolResult,
        latency_ms: int,
        retry_num: int,
        accepted: bool,
    ) -> None:
        entry = {
            "job_id": job_id,
            "agent_id": agent_id,
            "tool_name": tool_name,
            "input": input_data,
            "output": result.output,
            "error_code": result.error_code,
            "latency_ms": latency_ms,
            "retry_num": retry_num,
            "accepted": accepted,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self.tool_call_log.append(entry)
        logger.info(
            "tool_call",
            extra={k: v for k, v in entry.items() if k not in ("input", "output")},
        )

    async def execute_tool_sequence(
        self,
        tool_sequence: List[tuple[str, Dict]],
        context: Optional[SharedContext] = None,
    ) -> List[ToolResult]:
        results = []
        for tool_name, input_data in tool_sequence:
            result = await self.execute_tool(tool_name, input_data)
            results.append(result)
            if context is not None and result.success:
                tool = self.tools.get(tool_name)
                if tool:
                    context.add_tool_output(tool.to_tool_output(result, 0, input_data))
        return results

    def get_available_tools(self) -> List[str]:
        return list(self.tools.keys())

    def get_tool_stats(self) -> Dict[str, dict]:
        return {tool_name: tool.get_stats() for tool_name, tool in self.tools.items()}


def _classify_failure(result: ToolResult) -> str:
    """Map error codes to human-readable failure reasons."""
    mapping = {
        "EMPTY_RESULT": "empty results",
        "NO_RESULTS": "empty results",
        "TIMEOUT": "timeout",
        "SEARCH_TIMEOUT": "timeout",
        "MALFORMED_INPUT": "malformed input",
        "SECURITY_VIOLATION": "security violation",
        "EXECUTION_ERROR": "execution error",
        "TOOL_NOT_FOUND": "tool not found",
    }
    return mapping.get(result.error_code or "", result.message or "unknown failure")
