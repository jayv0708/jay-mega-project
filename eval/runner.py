"""Evaluation runner with LLM-as-a-judge."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.pipeline import DAGExecutor
from db.db import get_async_session
from db.models import Job, JobStatus
from agents.llm import AnthropicClient
from app.events import EventLogger

EVAL_DIMENSIONS = [
    "answer_correctness",
    "citation_accuracy",
    "contradiction_resolution_quality",
    "tool_selection_efficiency",
    "context_budget_compliance",
    "critique_agreement_rate",
]

CASES_DIR = Path(__file__).resolve().parent / "cases"
LATEST_EVAL_PATH = Path(__file__).resolve().parent / "latest_eval.json"

llm_judge = AnthropicClient()


def load_cases(directory: Path = CASES_DIR) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            cases.extend(loaded)
        else:
            cases.append(loaded)
    return sorted(cases, key=lambda item: item["case_id"])


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    job_id = str(uuid4())
    query = case["query"]
    
    # Save dummy job
    async with get_async_session() as session:
        job = Job(id=job_id, query=query, status=JobStatus.pending)
        session.add(job)
        await session.commit()
        
    event_logger = EventLogger()
    executor = DAGExecutor(job_id=job_id, event_logger=event_logger)
    
    try:
        await executor.execute_dag(query)
    except Exception as e:
        print(f"Error executing DAG for case {case['case_id']}: {e}")
        
    events = [event.model_dump(mode="json") for event in event_logger.memory_events_by_job.get(job_id, [])]
    
    final_answer = ""
    for event in reversed(events):
        if event["event_type"] == "JOB_COMPLETE":
            final_answer = event["data"].get("final_answer", "")
            break

    scores = await score_case_llm(case, events, final_answer)
    passed = all(score["score"] >= 0.65 for score in scores.values())
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "query": case["query"],
        "expected_answer": case.get("expected_answer"),
        "actual_answer": final_answer,
        "passed": passed,
        "scores": scores,
        "events": events,
    }


async def score_case_llm(case: dict[str, Any], events: list[dict[str, Any]], final_answer: str) -> dict[str, dict[str, Any]]:
    system_prompt = (
        "You are an impartial evaluator for an LLM orchestration system.\n"
        "Your goal is to grade the system's output and trace based on six dimensions.\n"
        "Output MUST be JSON conforming to the following structure:\n"
        "{\n"
        "  \"answer_correctness\": {\"score\": float 0-1, \"justification\": str},\n"
        "  \"citation_accuracy\": {\"score\": float 0-1, \"justification\": str},\n"
        "  \"contradiction_resolution_quality\": {\"score\": float 0-1, \"justification\": str},\n"
        "  \"tool_selection_efficiency\": {\"score\": float 0-1, \"justification\": str},\n"
        "  \"context_budget_compliance\": {\"score\": float 0-1, \"justification\": str},\n"
        "  \"critique_agreement_rate\": {\"score\": float 0-1, \"justification\": str}\n"
        "}"
    )

    user_prompt = (
        f"Query: {case['query']}\n"
        f"Expected Answer Hints: {case.get('expected_answer', 'None')}\n"
        f"Actual Final Answer: {final_answer}\n"
        f"Execution Trace Events (abridged): {json.dumps(events[:5] + events[-5:])}\n\n"
        "Please provide your JSON evaluation."
    )

    try:
        response = await llm_judge.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=800,
            fallback={
                "answer_correctness": {"score": 0.5, "justification": "LLM Judge Failed to parse"},
                "citation_accuracy": {"score": 0.5, "justification": "LLM Judge Failed to parse"},
                "contradiction_resolution_quality": {"score": 0.5, "justification": "LLM Judge Failed to parse"},
                "tool_selection_efficiency": {"score": 0.5, "justification": "LLM Judge Failed to parse"},
                "context_budget_compliance": {"score": 0.5, "justification": "LLM Judge Failed to parse"},
                "critique_agreement_rate": {"score": 0.5, "justification": "LLM Judge Failed to parse"}
            }
        )
        return response
    except Exception as e:
        print(f"Error scoring case {case['case_id']}: {e}")
        return {k: {"score": 0.0, "justification": str(e)} for k in EVAL_DIMENSIONS}


async def run_all_cases_async(cases_directory: Path = CASES_DIR, only_failed_from: dict[str, Any] | None = None) -> dict[str, Any]:
    cases = load_cases(cases_directory)
    if only_failed_from:
        failed_ids = {case["case_id"] for case in only_failed_from.get("cases", []) if not case.get("passed")}
        cases = [case for case in cases if case["case_id"] in failed_ids]
    
    # Run sequentially or in parallel; let's do sequentially to avoid rate limits or DB locks
    results = []
    for case in cases:
        results.append(await run_case(case))
        
    summary = summarize_results(results)
    run = {"run_id": str(uuid4()), "total_cases": len(results), "summary": summary, "cases": results}
    LATEST_EVAL_PATH.write_text(json.dumps(run, indent=2), encoding="utf-8")
    if only_failed_from is None:
        from eval.meta_loop import propose_rewrite
        propose_rewrite(run)
    return run


def run_all_cases(cases_directory: Path = CASES_DIR) -> dict[str, Any]:
    return asyncio.run(run_all_cases_async(cases_directory))


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, dict[str, Any]] = defaultdict(lambda: {"total": 0, "passed": 0})
    dimension_scores: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for result in results:
        category = by_category[result["category"]]
        category["total"] += 1
        category["passed"] += int(result["passed"])
        for dimension, score in result["scores"].items():
            dimension_scores[dimension].append((result["case_id"], score["score"]))
    by_dimension = {
        dimension: {
            "avg_score": sum(score for _, score in scores) / max(len(scores), 1),
            "failed_cases": [case_id for case_id, score in scores if score < 0.65],
        }
        for dimension, scores in dimension_scores.items()
    }
    return {"by_category": dict(by_category), "by_dimension": by_dimension}


def latest_run() -> dict[str, Any] | None:
    if not LATEST_EVAL_PATH.exists():
        return None
    return json.loads(LATEST_EVAL_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    print(json.dumps(run_all_cases(), indent=2))
