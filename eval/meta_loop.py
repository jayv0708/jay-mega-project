"""Self-improving prompt loop — database-backed rewrite store."""
from __future__ import annotations

import difflib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


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


# ──────────────────────────────────────────────────────────────────
# DB helpers (fail gracefully when DB is not available)
# ──────────────────────────────────────────────────────────────────

async def _db_insert_rewrite(rewrite: dict[str, Any]) -> None:
    """Persist a new rewrite record to PostgreSQL."""
    try:
        from db.db import get_async_session
        from db.models import PromptRewrite
        async with get_async_session() as session:
            row = PromptRewrite(
                id=rewrite["id"],
                eval_run_id=rewrite.get("run_id"),
                agent_id=rewrite["agent_id"],
                dimension=rewrite["dimension"],
                original_prompt=rewrite["original_prompt"],
                proposed_prompt=rewrite.get("proposed_prompt"),
                diff=rewrite.get("diff"),
                justification=rewrite.get("justification"),
                status=rewrite.get("status", "pending"),
            )
            session.add(row)
            await session.commit()
    except Exception as exc:
        # Fall through — local JSON store is maintained for tests without DB
        print(f"[meta_loop] DB insert failed (non-fatal): {exc}")


async def _db_update_rewrite(rewrite_id: str, updates: dict[str, Any]) -> None:
    """Update a rewrite row in PostgreSQL atomically."""
    try:
        from db.db import get_async_session
        from db.models import PromptRewrite
        from sqlalchemy import select, update
        async with get_async_session() as session:
            await session.execute(
                update(PromptRewrite)
                .where(PromptRewrite.id == rewrite_id)
                .values(**updates)
            )
            await session.commit()
    except Exception as exc:
        print(f"[meta_loop] DB update failed (non-fatal): {exc}")


async def list_rewrites_from_db() -> list[dict[str, Any]]:
    """Query all prompt rewrites from DB grouped by agent_id."""
    try:
        from db.db import get_async_session
        from db.models import PromptRewrite
        from sqlalchemy import select
        async with get_async_session() as session:
            rows = (await session.execute(
                select(PromptRewrite).order_by(PromptRewrite.agent_id, PromptRewrite.created_at)
            )).scalars().all()
            return [
                {
                    "id": str(row.id),
                    "eval_run_id": str(row.eval_run_id) if row.eval_run_id else None,
                    "agent_id": row.agent_id,
                    "dimension": row.dimension,
                    "status": row.status,
                    "justification": row.justification,
                    "performance_delta": row.performance_delta,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "approved_at": row.approved_at.isoformat() if row.approved_at else None,
                    "decided_by": row.decided_by,
                }
                for row in rows
            ]
    except Exception:
        # Fall back to JSON store
        return load_rewrites()


# ──────────────────────────────────────────────────────────────────
# JSON fall-back store (tests without PostgreSQL)
# ──────────────────────────────────────────────────────────────────

REWRITE_STORE = Path(__file__).resolve().parent / "prompt_rewrites.json"


def load_rewrites() -> list[dict[str, Any]]:
    import json
    if not REWRITE_STORE.exists():
        return []
    return json.loads(REWRITE_STORE.read_text(encoding="utf-8"))


def save_rewrites(rewrites: list[dict[str, Any]]) -> None:
    import json
    REWRITE_STORE.write_text(json.dumps(rewrites, indent=2), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────
# Core loop logic
# ──────────────────────────────────────────────────────────────────

def propose_rewrite(eval_run: dict[str, Any]) -> dict[str, Any] | None:
    import asyncio
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
    # Persist to JSON store synchronously (always available)
    rewrites = load_rewrites()
    rewrites.append(rewrite)
    save_rewrites(rewrites)
    # Attempt DB insert (best-effort async)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_db_insert_rewrite(rewrite))
        else:
            asyncio.run(_db_insert_rewrite(rewrite))
    except Exception:
        pass
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


async def decide_rewrite(
    rewrite_id: str,
    decision: str,
    decided_by: str,
    latest_run: dict[str, Any] | None,
) -> dict[str, Any]:
    from eval.runner import run_all_cases_async

    rewrites = load_rewrites()
    rewrite = next((item for item in rewrites if item["id"] == rewrite_id), None)
    if rewrite is None:
        raise KeyError(f"Rewrite {rewrite_id} not found")
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be 'approved' or 'rejected'")

    now = datetime.now(timezone.utc).isoformat()

    if decision == "rejected":
        rewrite["status"] = "rejected"
        rewrite.setdefault("history", []).append(
            {"decision": decision, "decided_by": decided_by, "decided_at": now}
        )
        save_rewrites(rewrites)
        await _db_update_rewrite(rewrite_id, {"status": "rejected", "decided_by": decided_by})
        return rewrite

    # Approved: run targeted re-eval on previously failed cases, compute delta
    prompt_path = PROMPT_FILE_MAP[rewrite["agent_id"]]
    original = prompt_path.read_text(encoding="utf-8")
    performance_delta: dict[str, Any] = {}
    try:
        prompt_path.write_text(rewrite["proposed_prompt"], encoding="utf-8")
        rerun = await run_all_cases_async(only_failed_from=latest_run)
        performance_delta = compute_delta(latest_run, rerun)
        positive = all(delta >= 0 for delta in performance_delta.values())
        rewrite["status"] = "approved" if positive else "rejected"
    finally:
        prompt_path.write_text(original, encoding="utf-8")

    rewrite["performance_delta"] = performance_delta
    rewrite["approved_at"] = now
    rewrite["decided_by"] = decided_by
    rewrite.setdefault("history", []).append(
        {
            "decision": decision,
            "decided_by": decided_by,
            "decided_at": now,
            "performance_delta": performance_delta,
        }
    )
    save_rewrites(rewrites)
    await _db_update_rewrite(
        rewrite_id,
        {
            "status": rewrite["status"],
            "performance_delta": performance_delta,
            "approved_at": datetime.now(timezone.utc),
            "decided_by": decided_by,
        },
    )
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
