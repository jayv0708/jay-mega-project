"""Tests for tool retry logging: TOOL_RETRY events, per-attempt DB records, TOOL_FAILURE."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from app.context import SharedContext
from tools import CodeSandboxTool, SelfReflectionTool, ToolOrchestrator, WebSearchTool
from tools.base import BaseTool, ToolResult


# ── Helpers ──────────────────────────────────────────────────────────────────

class AlwaysFailTool(BaseTool):
    """Simulates a tool that always returns empty results (insufficient)."""

    def __init__(self) -> None:
        super().__init__("AlwaysFailTool")
        self.call_count = 0
        self.received_inputs: list[Dict] = []

    async def execute(self, input_data: Dict[str, Any]) -> ToolResult:
        self.call_count += 1
        self.received_inputs.append(dict(input_data))
        return ToolResult(success=False, output={}, error_code="EMPTY_RESULT", message="empty results")


class SucceedOnAttemptTool(BaseTool):
    """Fails on first N attempts, then succeeds."""

    def __init__(self, succeed_on: int = 2) -> None:
        super().__init__("SucceedOnAttemptTool")
        self.call_count = 0
        self.succeed_on = succeed_on

    async def execute(self, input_data: Dict[str, Any]) -> ToolResult:
        self.call_count += 1
        if self.call_count >= self.succeed_on:
            return ToolResult(success=True, output={"results": ["found it"]})
        return ToolResult(success=False, output={}, error_code="EMPTY_RESULT", message="empty results")


collected_sse_events: list[Dict] = []


async def fake_emitter(*, event_type: str, agent_id: str, data: Any) -> None:
    collected_sse_events.append({"event_type": event_type, "agent_id": agent_id, "data": data})


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_sse_events():
    collected_sse_events.clear()
    yield


@pytest.mark.asyncio
async def test_web_search_fixture_returns_results():
    """Baseline: valid fixture query succeeds on attempt 0."""
    tool = WebSearchTool(Path("tools/search_fixture.json"))
    result = await tool.execute({"query": "orchestration"})
    assert result.success
    assert result.output["results"]


@pytest.mark.asyncio
async def test_code_sandbox_timeout_contract():
    """Infinite loop should be killed and return failure."""
    tool = CodeSandboxTool()
    result = await tool.execute({"code": "while True:\n    pass"})
    assert not result.success
    assert result.output.get("exit_code") == -1


@pytest.mark.asyncio
async def test_tool_retries_fire_with_modified_input():
    """Attempt 1 triggers TOOL_RETRY with modified_input, attempt 2 further modifies."""
    context = SharedContext(query="test")
    orchestrator = ToolOrchestrator(sse_emitter=fake_emitter)
    fail_tool = AlwaysFailTool()
    orchestrator.register_tool(fail_tool)

    result = await orchestrator.execute_tool_with_retries(
        "AlwaysFailTool",
        {"query": "original query"},
        agent_id="rag",
        job_id=str(context.job_id),
        context=context,
    )

    # Tool was called 3 times (attempt 0, 1, 2)
    assert fail_tool.call_count == 3

    # retry_hint added on retries
    assert "retry_hint" in fail_tool.received_inputs[1]
    assert fail_tool.received_inputs[1]["retry_hint"]["retry_num"] == 1
    assert "retry_hint" in fail_tool.received_inputs[2]
    assert fail_tool.received_inputs[2]["retry_hint"]["retry_num"] == 2

    # input was modified between retries (query broadened on attempt 1)
    assert fail_tool.received_inputs[1]["query"] != fail_tool.received_inputs[0]["query"]


@pytest.mark.asyncio
async def test_tool_failure_event_fires_after_all_retries():
    """TOOL_FAILURE SSE event must fire after the 3rd failed attempt."""
    orchestrator = ToolOrchestrator(sse_emitter=fake_emitter)
    orchestrator.register_tool(AlwaysFailTool())

    await orchestrator.execute_tool_with_retries(
        "AlwaysFailTool",
        {"query": "fail"},
        agent_id="rag",
        job_id="test-job-123",
    )

    event_types = [e["event_type"] for e in collected_sse_events]
    assert "TOOL_RETRY" in event_types, "TOOL_RETRY event must be emitted on retry"
    assert "TOOL_FAILURE" in event_types, "TOOL_FAILURE event must be emitted after final retry"

    retry_events = [e for e in collected_sse_events if e["event_type"] == "TOOL_RETRY"]
    assert len(retry_events) == 2, "Exactly 2 TOOL_RETRY events (after attempt 0 and 1)"
    assert retry_events[0]["data"]["attempt"] == 1
    assert retry_events[1]["data"]["attempt"] == 2


@pytest.mark.asyncio
async def test_all_attempts_individually_logged():
    """All 3 attempts must be individually present in the tool_call_log."""
    orchestrator = ToolOrchestrator(sse_emitter=fake_emitter)
    orchestrator.register_tool(AlwaysFailTool())

    await orchestrator.execute_tool_with_retries(
        "AlwaysFailTool",
        {"query": "logged"},
        agent_id="rag",
        job_id="log-test-job",
    )

    log = orchestrator.tool_call_log
    assert len(log) == 3, f"Expected 3 log entries, got {len(log)}"
    assert log[0]["retry_num"] == 0
    assert log[1]["retry_num"] == 1
    assert log[2]["retry_num"] == 2
    for entry in log:
        assert not entry["accepted"]
        assert entry["tool_name"] == "AlwaysFailTool"
        assert entry["agent_id"] == "rag"


@pytest.mark.asyncio
async def test_success_on_second_attempt_stops_retries():
    """If tool succeeds on attempt 2, no TOOL_FAILURE is emitted."""
    orchestrator = ToolOrchestrator(sse_emitter=fake_emitter)
    orchestrator.register_tool(SucceedOnAttemptTool(succeed_on=2))

    result = await orchestrator.execute_tool_with_retries(
        "SucceedOnAttemptTool",
        {"query": "test"},
        agent_id="rag",
        job_id="success-job",
    )

    assert result.success
    event_types = [e["event_type"] for e in collected_sse_events]
    assert "TOOL_RETRY" in event_types
    assert "TOOL_FAILURE" not in event_types


@pytest.mark.asyncio
async def test_self_reflection_reads_shared_context():
    context = SharedContext(query="reflect")
    from app.context import AgentOutput

    context.agent_outputs = {
        "a": AgentOutput(agent_id="a", output="Claim A"),
        "b": AgentOutput(agent_id="b", output="Claim B"),
    }
    result = await SelfReflectionTool().execute({"shared_context": context})

    assert result.success
    assert result.output["contradictions"]


@pytest.mark.asyncio
async def test_tool_orchestrator_retry_logs_three_entries():
    """Legacy test — alias for all_attempts_individually_logged."""
    context = SharedContext(query="test")
    orchestrator = ToolOrchestrator(sse_emitter=fake_emitter)
    orchestrator.register_tool(WebSearchTool(Path("missing.json")))

    result = await orchestrator.execute_tool_with_retries(
        "WebSearchTool",
        {"query": "missing"},
        agent_id="rag",
        job_id=str(context.job_id),
        context=context,
    )

    assert not result.success
    assert len(orchestrator.tool_call_log) == 3
    assert orchestrator.tool_call_log[0]["retry_num"] == 0
