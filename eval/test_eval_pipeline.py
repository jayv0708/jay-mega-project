from eval.runner import EVAL_DIMENSIONS, load_cases, run_all_cases


def test_eval_fixture_count_is_15():
    cases = load_cases()
    assert len(cases) == 15
    assert {case["category"] for case in cases} == {"baseline", "ambiguous", "adversarial"}


def test_eval_pipeline_scores_all_dimensions():
    run = run_all_cases()

    assert run["total_cases"] == 15
    for case in run["cases"]:
        assert set(case["scores"]) == set(EVAL_DIMENSIONS)
        for score in case["scores"].values():
            assert 0.0 <= score["score"] <= 1.0
            assert score["justification"]
