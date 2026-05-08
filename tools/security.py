"""
Security hardening layer.

Provides prompt injection detection, input sanitisation, and policy audit logging.
Every tool input and retrieved chunk passes through this layer before execution.

Design principles:
- Heuristic detection first (cheap, deterministic).
- Audit every rejection — observable and replayable.
- Never silently swallow input; always surface why it was rejected.
"""

from __future__ import annotations

import re
import structlog
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Injection heuristics
# ---------------------------------------------------------------------------

# Patterns that indicate an attempt to subvert system instructions.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|earlier|above)\s+instructions", re.I),
    re.compile(r"forget\s+(everything|your\s+instructions)", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"disregard\s+(your|the)\s+(system|previous)\s+(prompt|instructions)", re.I),
    re.compile(r"new\s+persona", re.I),
    re.compile(r"(reveal|print|output|show)\s+(your\s+)?(system\s+|hidden\s+)?prompt", re.I),
    re.compile(r"act\s+as\s+if\s+you\s+(have\s+no|don't\s+have)", re.I),
    re.compile(r"bypass\s+(safety|security|eval|guard)", re.I),
    re.compile(r"mark\s+every\s+(eval|test|case)\s+as\s+passed", re.I),
    re.compile(r"<\|im_start\|>|<\|im_sep\|>|<\|im_end\|>", re.I),  # token injection
    re.compile(r"\[INST\]|\[/INST\]", re.I),                          # Llama token injection
]

# Patterns that indicate suspicious tool misuse.
_SHELL_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[;&|`$]"),                                           # shell metacharacters
    re.compile(r"\.\.\s*/"),                                          # path traversal
    re.compile(r"(rm|del|format|mkfs|dd)\s+", re.I),                 # destructive commands
    re.compile(r"(import|__import__)\s+os", re.I),
    re.compile(r"subprocess|popen|exec\(|eval\(", re.I),
    re.compile(r"open\(['\"]/(etc|proc|sys|root)", re.I),            # privileged file access
]

# ---------------------------------------------------------------------------
# Retrieval poisoning heuristics
# ---------------------------------------------------------------------------

_RETRIEVAL_POISON_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous", re.I),
    re.compile(r"(you\s+are|pretend\s+to\s+be)\s+", re.I),
    re.compile(r"<\|.*?\|>", re.I),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SecurityViolation:
    kind: str                        # "prompt_injection" | "shell_injection" | "retrieval_poison"
    pattern: str                     # which heuristic triggered
    snippet: str                     # offending substring (truncated for safety)
    source: str                      # "tool_input" | "retrieval_chunk"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class InspectionResult:
    safe: bool
    violations: list[SecurityViolation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inspect_tool_input(tool_name: str, input_data: Any, job_id: str | None = None) -> InspectionResult:
    """
    Inspect tool input for prompt injection and shell injection.
    Returns InspectionResult with all violations found.
    """
    text = _flatten_to_text(input_data)
    violations: list[SecurityViolation] = []

    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            v = SecurityViolation(
                kind="prompt_injection",
                pattern=pattern.pattern,
                snippet=text[max(0, m.start() - 20): m.end() + 20],
                source="tool_input",
            )
            violations.append(v)
            logger.warning(
                "security.prompt_injection_detected",
                tool=tool_name,
                job_id=job_id,
                pattern=pattern.pattern,
                snippet=v.snippet,
            )

    # Code sandbox gets extra shell-injection checks
    if tool_name == "CodeSandboxTool":
        code = input_data.get("code", "") if isinstance(input_data, dict) else text
        for pattern in _SHELL_INJECTION_PATTERNS:
            m = pattern.search(code)
            if m:
                v = SecurityViolation(
                    kind="shell_injection",
                    pattern=pattern.pattern,
                    snippet=code[max(0, m.start() - 10): m.end() + 10],
                    source="tool_input",
                )
                violations.append(v)
                logger.warning(
                    "security.shell_injection_detected",
                    tool=tool_name,
                    job_id=job_id,
                    pattern=pattern.pattern,
                )

    return InspectionResult(safe=len(violations) == 0, violations=violations)


def inspect_retrieval_chunk(chunk_text: str, chunk_id: str, job_id: str | None = None) -> InspectionResult:
    """
    Scan a retrieved document chunk for embedded injection payloads
    (retrieval poisoning / indirect prompt injection).
    """
    violations: list[SecurityViolation] = []
    for pattern in _RETRIEVAL_POISON_PATTERNS:
        m = pattern.search(chunk_text)
        if m:
            v = SecurityViolation(
                kind="retrieval_poison",
                pattern=pattern.pattern,
                snippet=chunk_text[max(0, m.start() - 20): m.end() + 20],
                source="retrieval_chunk",
            )
            violations.append(v)
            logger.warning(
                "security.retrieval_poison_detected",
                chunk_id=chunk_id,
                job_id=job_id,
                pattern=pattern.pattern,
            )
    return InspectionResult(safe=len(violations) == 0, violations=violations)


def sanitize_text(text: str) -> str:
    """
    Strip known injection tokens from user-visible text.
    Does NOT silently truncate; returns sanitised copy.
    """
    sanitised = text
    for pattern in _INJECTION_PATTERNS:
        sanitised = pattern.sub("[REDACTED]", sanitised)
    return sanitised


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flatten_to_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return " ".join(str(v) for v in data.values())
    if isinstance(data, (list, tuple)):
        return " ".join(str(item) for item in data)
    return str(data)
