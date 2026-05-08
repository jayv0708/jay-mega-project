from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict

from tools.base import BaseTool, ToolResult
from agents.llm import AnthropicClient


class NLToSQLTool(BaseTool):
    def __init__(self, fixture_db: Path) -> None:
        super().__init__("NLToSQLTool")
        self.fixture_db = fixture_db
        self.llm = AnthropicClient()

    async def execute(self, input_data: Dict[str, Any]) -> ToolResult:
        if not isinstance(input_data, dict) or "query" not in input_data:
            return self.on_malformed_input()

        sql_used = input_data.get("sql")
        if not sql_used:
            generated = await self.llm.complete_json(
                "Convert natural language to SQLite SQL. Return JSON only: {\"sql\": \"...\"}.",
                str(input_data["query"]),
                temperature=0.0,
                max_tokens=256,
                fallback={"sql": "SELECT 1 AS value"},
            )
            sql_used = generated.get("sql", "SELECT 1 AS value")
        try:
            with sqlite3.connect(self.fixture_db) as conn:
                cursor = conn.execute(sql_used)
                rows = [dict(row) for row in map(lambda r: dict(zip([c[0] for c in cursor.description], r)), cursor.fetchall())]
                return ToolResult(
                    success=True,
                    output={
                        "rows": rows,
                        "sql_used": sql_used,
                        "row_count": len(rows),
                    },
                )
        except sqlite3.Error as exc:
            return ToolResult(
                success=False,
                output={"rows": [], "error_code": "INVALID_SQL", "sql_used": sql_used},
                error_code="INVALID_SQL",
                message=str(exc),
            )

    def on_malformed_input(self) -> ToolResult:
        return ToolResult(
            success=False,
            output={"rows": [], "error_code": "INVALID_SQL", "sql_used": ""},
            error_code="INVALID_SQL",
            message="Invalid SQL tool input.",
        )
