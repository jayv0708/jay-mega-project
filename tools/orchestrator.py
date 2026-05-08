"""Tool orchestration and management."""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.context import SharedContext

from tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ToolOrchestrator:
    """Manages the execution of tools with error handling and state management."""

    def __init__(self) -> None:
        self.tools: Dict[str, BaseTool] = {}
        self.tool_call_log: List[Dict] = []

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool for use."""
        self.tools[tool.tool_name] = tool
        logger.debug(f"Registered tool '{tool.tool_name}'")

    def unregister_tool(self, tool_name: str) -> None:
        """Unregister a tool."""
        if tool_name in self.tools:
            del self.tools[tool_name]
            logger.debug(f"Unregistered tool '{tool_name}'")

    async def _execute_registered_tool(self, tool_name: str, input_data: Dict) -> tuple[ToolResult, int]:
        tool = self.tools[tool_name]
        logger.info(f"Executing tool '{tool_name}'")
        result, latency_ms = await tool._execute_with_tracking(input_data)
        logger.debug(f"Tool '{tool_name}' completed in {latency_ms}ms")
        return result, latency_ms

    async def execute_tool(self, tool_name: str, input_data: Dict) -> ToolResult:
        """Execute a specific tool by name.
        
        Args:
            tool_name: The name of the tool to execute
            input_data: Input parameters for the tool
            
        Returns:
            ToolResult with success status and output
        """
        if tool_name not in self.tools:
            logger.warning(f"Tool '{tool_name}' not found")
            return ToolResult(
                success=False,
                output={},
                error_code="TOOL_NOT_FOUND",
                message=f"Tool '{tool_name}' not registered"
            )

        try:
            result, _ = await self._execute_registered_tool(tool_name, input_data)
            return result
        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}", exc_info=True)
            return ToolResult(
                success=False,
                output={},
                error_code="EXECUTION_ERROR",
                message=str(e)
            )

    async def execute_tool_with_retries(
        self,
        tool_name: str,
        input_data: Dict,
        *,
        agent_id: str,
        job_id: str,
        context: Optional[SharedContext] = None,
    ) -> ToolResult:
        current_input = dict(input_data)
        last_result: ToolResult | None = None
        for retry_num in range(3):
            result, latency_ms = await self._execute_once_for_log(tool_name, current_input)
            accepted = result.success
            self._log_tool_call(
                job_id=job_id,
                agent_id=agent_id,
                tool_name=tool_name,
                input_data=current_input,
                result=result,
                latency_ms=latency_ms,
                retry_num=retry_num,
                accepted=accepted,
            )
            if context is not None:
                tool = self.tools.get(tool_name)
                if tool:
                    context.add_tool_output(tool.to_tool_output(result, latency_ms, current_input))
            if accepted:
                return result
            last_result = result
            current_input = self._modify_input_for_retry(current_input, result, retry_num)
        return last_result or ToolResult(success=False, output={}, error_code="NO_ATTEMPT", message="Tool was not attempted")

    async def _execute_once_for_log(self, tool_name: str, input_data: Dict) -> tuple[ToolResult, int]:
        if tool_name not in self.tools:
            return (
                ToolResult(success=False, output={}, error_code="TOOL_NOT_FOUND", message=f"Tool '{tool_name}' not registered"),
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
            next_input["query"] = str(next_input["query"]).strip()
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
        self.tool_call_log.append(
            {
                "job_id": job_id,
                "agent_id": agent_id,
                "tool_name": tool_name,
                "input": input_data,
                "output": result.output,
                "latency_ms": latency_ms,
                "retry_num": retry_num,
                "accepted": accepted,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def execute_tool_sequence(
        self, 
        tool_sequence: List[tuple[str, Dict]],
        context: Optional[SharedContext] = None
    ) -> List[ToolResult]:
        """Execute a sequence of tools in order.
        
        Args:
            tool_sequence: List of (tool_name, input_data) tuples
            context: Optional shared context to update with tool outputs
            
        Returns:
            List of ToolResults in execution order
        """
        results = []
        for tool_name, input_data in tool_sequence:
            if tool_name not in self.tools:
                result = ToolResult(
                    success=False,
                    output={},
                    error_code="TOOL_NOT_FOUND",
                    message=f"Tool '{tool_name}' not registered"
                )
                latency_ms = 0
            else:
                try:
                    result, latency_ms = await self._execute_registered_tool(tool_name, input_data)
                except Exception as e:
                    logger.error(f"Error executing tool '{tool_name}': {e}", exc_info=True)
                    result = ToolResult(
                        success=False,
                        output={},
                        error_code="EXECUTION_ERROR",
                        message=str(e)
                    )
                    latency_ms = 0
            results.append(result)
            
            if context is not None and result.success:
                tool = self.tools.get(tool_name)
                if tool:
                    context.add_tool_output(tool.to_tool_output(result, latency_ms, input_data))

        return results

    def get_available_tools(self) -> List[str]:
        """Get list of available tool names."""
        return list(self.tools.keys())

    def get_tool_stats(self) -> Dict[str, dict]:
        """Get statistics for all registered tools."""
        return {tool_name: tool.get_stats() for tool_name, tool in self.tools.items()}
