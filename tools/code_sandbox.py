from __future__ import annotations

import tempfile
from pathlib import Path
from time import perf_counter
from typing import Any, Dict

import docker
from docker.errors import DockerException, ContainerError

from tools.base import BaseTool, ToolResult


class CodeSandboxTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("CodeSandboxTool")
        try:
            self.client = docker.from_env()
        except DockerException:
            self.client = None

    async def execute(self, input_data: Dict[str, Any]) -> ToolResult:
        if not isinstance(input_data, dict) or "code" not in input_data:
            return self.on_malformed_input()

        code = input_data["code"]

        if self.client is None:
            # Fallback for environments where docker is installing or unavailable
            return ToolResult(
                success=False,
                output={"stdout": "", "stderr": "Docker daemon not available for sandboxing.", "exit_code": -1},
                error_code="DOCKER_NOT_AVAILABLE",
                message="Docker daemon is not available on this host. Cannot execute untrusted code.",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox_file = Path(tmpdir) / "sandbox.py"
            sandbox_file.write_text(code, encoding="utf-8")
            start = perf_counter()

            try:
                # Run the python script in an isolated docker container
                # Note: `user="1000:1000"` might fail if 1000 doesn't exist in the base image, but it's typically fine for uid
                output = self.client.containers.run(
                    "python:3.12-slim",
                    command=["python", "/app/sandbox.py"],
                    volumes={tmpdir: {"bind": "/app", "mode": "ro"}},
                    working_dir="/app",
                    network_mode="none",     # Drop all networking
                    mem_limit="128m",        # Hard memory limit
                    cpu_quota=50000,         # 50% CPU limit
                    pids_limit=10,           # Prevent fork bombs
                    read_only=True,          # Mount root as read-only
                    security_opt=["no-new-privileges"], 
                    detach=False,
                    stdout=True,
                    stderr=True,
                    remove=True,             # Clean up container
                    user="1000:1000",        # Run as non-root user
                )
                
                latency_ms = int((perf_counter() - start) * 1000)
                return ToolResult(
                    success=True,
                    output={
                        "stdout": output.decode("utf-8") if isinstance(output, bytes) else str(output),
                        "stderr": "",
                        "exit_code": 0,
                        "execution_time_ms": latency_ms,
                    },
                )
            except ContainerError as e:
                latency_ms = int((perf_counter() - start) * 1000)
                return ToolResult(
                    success=False,
                    output={
                        "stdout": "",
                        "stderr": e.stderr.decode("utf-8") if isinstance(e.stderr, bytes) else str(e.stderr),
                        "exit_code": e.exit_status,
                        "execution_time_ms": latency_ms,
                    },
                    error_code="RUNTIME_ERROR",
                    message="Code execution failed inside sandbox",
                )
            except DockerException as e:
                return ToolResult(
                    success=False,
                    output={"stdout": "", "stderr": str(e), "exit_code": -1},
                    error_code="SANDBOX_ERROR",
                    message=f"Failed to run sandbox container: {e}",
                )

    def on_timeout(self) -> ToolResult:
        return ToolResult(
            success=False,
            output={"stdout": "", "stderr": "Execution timed out", "exit_code": -1},
            error_code="TIMEOUT",
            message="Execution timed out",
        )
