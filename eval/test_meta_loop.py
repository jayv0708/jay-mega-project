import pytest

from eval.meta_loop import decide_rewrite, get_rewrite, load_rewrites
from eval.runner import latest_run, run_all_cases, run_all_cases_async


def test_meta_agent_proposes_pending_rewrite_after_eval():
    run = run_all_cases()
    rewrites = load_rewrites()

    assert run["run_id"]
    assert rewrites
    assert rewrites[-1]["status"] == "pending"
    assert rewrites[-1]["diff"]


@pytest.mark.asyncio
async def test_rewrite_rejection_records_history():
    await run_all_cases_async()
    rewrite = load_rewrites()[-1]

    updated = await decide_rewrite(rewrite["id"], "reject", "Not good enough", latest_run())

    assert updated["status"] == "rejected"
    assert get_rewrite(rewrite["id"])["history"][-1]["notes"] == "Not good enough"
