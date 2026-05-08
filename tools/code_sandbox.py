from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from time import perf_counter
from typing import Any, Dict

from tools.base import BaseTool, ToolResult


class CodeSandboxTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("CodeSandboxTool")

    async def execute(self, input_data: Dict[str, Any]) -> ToolResult:
        if not isinstance(input_data, dict) or "code" not in input_data:
            return self.on_malformed_input()

        code = input_data["code"]
        forbidden = ["socket", "requests", "urllib", "open(", "Path(", "os.remove", "shutil", "subprocess"]
        if any(term in code for term in forbidden):
            return ToolResult(
                success=False,
                output={"stdout": "", "stderr": "Sandbox policy blocked network or filesystem access.", "exit_code": -2},
                error_code="SANDBOX_POLICY_VIOLATION",
                message="Sandbox policy blocked network or filesystem access.",
            )
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox_file = Path(tmpdir) / "sandbox.py"
            sandbox_file.write_text(code, encoding="utf-8")
            start = perf_counter()
            try:
                proc = subprocess.run(
                    ["python", str(sandbox_file)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=tmpdir,
                )
                latency_ms = int((perf_counter() - start) * 1000)
                return ToolResult(
                    success=True,
                    output={
                        "stdout": proc.stdout,
                        "stderr": proc.stderr,
                        "exit_code": proc.returncode,
                        "execution_time_ms": latency_ms,
                    },
                )
            except subprocess.TimeoutExpired:
                return self.on_timeout()
            except Exception as exc:
                return ToolResult(success=False, output={}, error_code="RUNTIME_ERROR", message=str(exc))

    def on_timeout(self) -> ToolResult:
        return ToolResult(
            success=False,
            output={"stdout": "", "stderr": "Execution timed out", "exit_code": -1},
            error_code="TIMEOUT",
            message="Execution timed out",
        )
