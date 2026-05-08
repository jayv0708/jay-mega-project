"""Evaluation runner with LLM-as-a-judge and PostgreSQL persistence."""

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
        if path.name == "README.md":
            continue
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            cases.extend(loaded)
        else:
            cases.append(loaded)
    return sorted(cases, key=lambda item: item["case_id"])


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    job_id = str(uuid4())
    query = case["query"]

    # Save dummy job (gracefully skipped if DB unavailable)
    try:
        async with get_async_session() as session:
            job = Job(id=job_id, query=query, status=JobStatus.pending)
            session.add(job)
            await session.commit()
    except Exception:
        pass

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
        "adversarial_type": case.get("adversarial_type"),
        "expected_answer": case.get("expected_answer_contains"),
        "actual_answer": final_answer,
        "passed": passed,
        "scores": scores,
        "events": events,
    }


async def score_case_llm(
    case: dict[str, Any], events: list[dict[str, Any]], final_answer: str
) -> dict[str, dict[str, Any]]:
    # Deterministic fallback — no API key needed for tests
    fallback = {dim: {"score": 0.75, "justification": "Deterministic fixture score (no API key)"} for dim in EVAL_DIMENSIONS}

    # Validate citation_accuracy: check provenance_map coverage
    provenance_map: list[dict] = []
    for event in reversed(events):
        if event.get("event_type") == "JOB_COMPLETE":
            provenance_map = event.get("data", {}).get("provenance_map", [])
            break

    system_prompt = (
        "You are an impartial evaluator for an LLM orchestration system.\n"
        "Grade the system output across six dimensions.\n"
        "Output MUST be valid JSON:\n"
        "{\n"
        '  "answer_correctness": {"score": float 0-1, "justification": str},\n'
        '  "citation_accuracy": {"score": float 0-1, "justification": str},\n'
        '  "contradiction_resolution_quality": {"score": float 0-1, "justification": str},\n'
        '  "tool_selection_efficiency": {"score": float 0-1, "justification": str},\n'
        '  "context_budget_compliance": {"score": float 0-1, "justification": str},\n'
        '  "critique_agreement_rate": {"score": float 0-1, "justification": str}\n'
        "}"
    )

    # Citation accuracy penalty: count missing provenance entries
    sentences_in_answer = [s.strip() for s in final_answer.split(".") if s.strip()] if final_answer else []
    missing_prov = max(0, len(sentences_in_answer) - len(provenance_map))
    prov_note = (
        f" Note: {missing_prov} sentence(s) in final_answer lack provenance_map entries."
        if missing_prov > 0
        else " All sentences have provenance_map entries."
    )

    user_prompt = (
        f"Query: {case['query']}\n"
        f"Expected Keywords: {case.get('expected_answer_contains', 'None')}\n"
        f"Adversarial Type: {case.get('adversarial_type', 'None')}\n"
        f"Actual Final Answer: {final_answer}\n"
        f"Provenance Map Entries: {len(provenance_map)}{prov_note}\n"
        f"Execution Trace (abridged): {json.dumps(events[:5] + events[-5:])}\n\n"
        "Provide your JSON evaluation."
    )

    try:
        response = await llm_judge.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=800,
            fallback=fallback,
        )
        # Validate citation_accuracy: penalize missing provenance
        if missing_prov > 0 and "citation_accuracy" in response:
            existing_score = response["citation_accuracy"].get("score", 0.75)
            penalty = min(0.3, missing_prov * 0.1)
            response["citation_accuracy"]["score"] = max(0.0, existing_score - penalty)
            response["citation_accuracy"]["justification"] += (
                f" PENALIZED: {missing_prov} sentence(s) missing from provenance_map."
            )
            
        # Deterministic overrides
        from eval.scoring import score_tool_selection_efficiency, score_budget_compliance
        response["tool_selection_efficiency"] = score_tool_selection_efficiency(events)
        response["context_budget_compliance"] = score_budget_compliance(events)
        
        return response
    except Exception as e:
        print(f"Error scoring case {case['case_id']}: {e}")
        return {k: {"score": 0.0, "justification": str(e)} for k in EVAL_DIMENSIONS}


async def _persist_eval_run(run: dict[str, Any]) -> None:
    """Best-effort persist eval run to PostgreSQL."""
    try:
        from db.db import get_async_session
        from db.models import EvalRun
        summary = run.get("summary", {})
        async with get_async_session() as session:
            row = EvalRun(
                id=run["run_id"],
                total_cases=run["total_cases"],
                category_breakdown=summary.get("by_category"),
                dimension_scores=summary.get("by_dimension"),
                test_case_results=run.get("cases"),
                summary=summary,
            )
            session.add(row)
            await session.commit()
    except Exception as exc:
        print(f"[runner] DB persist failed (non-fatal): {exc}")


async def run_all_cases_async(
    cases_directory: Path = CASES_DIR,
    only_failed_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cases = load_cases(cases_directory)
    if only_failed_from:
        failed_ids = {
            case["case_id"]
            for case in only_failed_from.get("cases", [])
            if not case.get("passed")
        }
        cases = [case for case in cases if case["case_id"] in failed_ids]

    results = []
    for case in cases:
        results.append(await run_case(case))

    summary = summarize_results(results)
    run = {
        "run_id": str(uuid4()),
        "run_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "total_cases": len(results),
        "summary": summary,
        "cases": results,
    }
    LATEST_EVAL_PATH.write_text(json.dumps(run, indent=2), encoding="utf-8")
    if only_failed_from is None:
        from eval.meta_loop import propose_rewrite
        propose_rewrite(run)
    # Persist to DB (best-effort)
    await _persist_eval_run(run)
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

    by_dimension: dict[str, dict[str, Any]] = {}
    for dimension, scores in dimension_scores.items():
        avg = sum(s for _, s in scores) / max(len(scores), 1)
        failed = [case_id for case_id, s in scores if s < 0.65]
        min_score = min((s for _, s in scores), default=avg)
        worst = next((case_id for case_id, s in scores if s == min_score), None)
        by_dimension[dimension] = {
            "avg_score": avg,
            "avg": avg,
            "min": min_score,
            "worst_case_id": worst,
            "failed_cases": failed,
        }

    return {"by_category": dict(by_category), "by_dimension": by_dimension}


def latest_run() -> dict[str, Any] | None:
    if not LATEST_EVAL_PATH.exists():
        return None
    return json.loads(LATEST_EVAL_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    print(json.dumps(run_all_cases(), indent=2))
