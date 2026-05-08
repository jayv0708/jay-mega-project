from pathlib import Path

import pytest

from app.context import SharedContext
from tools import CodeSandboxTool, SelfReflectionTool, ToolOrchestrator, WebSearchTool


@pytest.mark.asyncio
async def test_web_search_fixture_returns_results():
    tool = WebSearchTool(Path("tools/search_fixture.json"))
    result = await tool.execute({"query": "orchestration"})

    assert result.success
    assert result.output["results"]


@pytest.mark.asyncio
async def test_code_sandbox_timeout_contract():
    tool = CodeSandboxTool()
    result = await tool.execute({"code": "while True:\n    pass"})

    assert not result.success
    assert result.output["exit_code"] == -1


@pytest.mark.asyncio
async def test_tool_orchestrator_logs_retries():
    context = SharedContext(query="test")
    orchestrator = ToolOrchestrator()
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
