from __future__ import annotations

import difflib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


REWRITE_STORE = Path(__file__).resolve().parent / "prompt_rewrites.json"
PROMPT_DIR = Path(__file__).resolve().parents[1] / "agents" / "prompts"


DIMENSION_AGENT_MAP = {
    "answer_correctness": "synthesis",
    "citation_accuracy": "rag",
    "contradiction_resolution_quality": "synthesis",
    "tool_selection_efficiency": "orchestrator",
    "context_budget_compliance": "compression",
    "critique_agreement_rate": "critique",
}


PROMPT_FILE_MAP = {
    "orchestrator": PROMPT_DIR / "orchestrator.json",
    "rag": PROMPT_DIR / "rag.txt",
    "critique": PROMPT_DIR / "critique.txt",
    "synthesis": PROMPT_DIR / "synthesis.txt",
    "compression": PROMPT_DIR / "compression.txt",
}


def load_rewrites() -> list[dict[str, Any]]:
    if not REWRITE_STORE.exists():
        return []
    return json.loads(REWRITE_STORE.read_text(encoding="utf-8"))


def save_rewrites(rewrites: list[dict[str, Any]]) -> None:
    REWRITE_STORE.write_text(json.dumps(rewrites, indent=2), encoding="utf-8")


def propose_rewrite(eval_run: dict[str, Any]) -> dict[str, Any] | None:
    failed_cases = [case for case in eval_run.get("cases", []) if not case.get("passed")]
    if not failed_cases:
        return None

    worst_dimension = find_worst_dimension(failed_cases)
    agent_id = DIMENSION_AGENT_MAP.get(worst_dimension, "synthesis")
    prompt_path = PROMPT_FILE_MAP[agent_id]
    original_prompt = prompt_path.read_text(encoding="utf-8")
    proposed_prompt = build_candidate_prompt(original_prompt, worst_dimension)
    unified_diff = "\n".join(
        difflib.unified_diff(
            original_prompt.splitlines(),
            proposed_prompt.splitlines(),
            fromfile=str(prompt_path),
            tofile=f"{prompt_path}.candidate",
            lineterm="",
        )
    )
    rewrite = {
        "id": str(uuid4()),
        "run_id": eval_run["run_id"],
        "agent_id": agent_id,
        "dimension": worst_dimension,
        "original_prompt": original_prompt,
        "proposed_prompt": proposed_prompt,
        "diff": unified_diff,
        "justification": f"Failed cases were weakest on {worst_dimension}; {agent_id} owns that behavior.",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "history": [],
        "failed_case_ids": [case["case_id"] for case in failed_cases],
    }
    rewrites = load_rewrites()
    rewrites.append(rewrite)
    save_rewrites(rewrites)
    return rewrite


def find_worst_dimension(failed_cases: list[dict[str, Any]]) -> str:
    totals: dict[str, list[float]] = {}
    for case in failed_cases:
        for dimension, result in case["scores"].items():
            totals.setdefault(dimension, []).append(result["score"])
    averages = {dimension: sum(scores) / len(scores) for dimension, scores in totals.items()}
    return min(averages, key=averages.get)


def build_candidate_prompt(original_prompt: str, dimension: str) -> str:
    return (
        original_prompt.rstrip()
        + f"\n\nCandidate improvement: prioritize {dimension}, cite supporting context, and expose uncertainty explicitly.\n"
    )


async def decide_rewrite(rewrite_id: str, decision: str, notes: str, latest_run: dict[str, Any] | None) -> dict[str, Any]:
    from eval.runner import run_all_cases_async

    rewrites = load_rewrites()
    rewrite = next((item for item in rewrites if item["id"] == rewrite_id), None)
    if rewrite is None:
        raise KeyError(f"Rewrite {rewrite_id} not found")
    if decision not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")

    history_record = {
        "decision": decision,
        "notes": notes,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "delta_scores": {},
    }

    if decision == "reject":
        rewrite["status"] = "rejected"
        rewrite["history"].append(history_record)
        save_rewrites(rewrites)
        return rewrite

    prompt_path = PROMPT_FILE_MAP[rewrite["agent_id"]]
    original = prompt_path.read_text(encoding="utf-8")
    try:
        prompt_path.write_text(rewrite["proposed_prompt"], encoding="utf-8")
        rerun = await run_all_cases_async(only_failed_from=latest_run)
        history_record["delta_scores"] = compute_delta(latest_run, rerun)
        positive = all(delta >= 0 for delta in history_record["delta_scores"].values())
        rewrite["status"] = "approved" if positive else "rejected"
    finally:
        prompt_path.write_text(original, encoding="utf-8")
    rewrite["history"].append(history_record)
    save_rewrites(rewrites)
    return rewrite


def compute_delta(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, float]:
    if not before:
        return {}
    before_scores = before.get("summary", {}).get("by_dimension", {})
    after_scores = after.get("summary", {}).get("by_dimension", {})
    return {
        dimension: after_scores.get(dimension, {}).get("avg_score", 0.0) - before_scores.get(dimension, {}).get("avg_score", 0.0)
        for dimension in set(before_scores) | set(after_scores)
    }


def get_rewrite(rewrite_id: str) -> dict[str, Any] | None:
    return next((item for item in load_rewrites() if item["id"] == rewrite_id), None)
