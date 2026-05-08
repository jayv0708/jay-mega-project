from fastapi.testclient import TestClient

from api.main import app
from eval.runner import run_all_cases
from eval.meta_loop import load_rewrites


def test_application_endpoint_contract_has_exactly_five_paths():
    paths = {
        route.path
        for route in app.routes
        if getattr(route, "include_in_schema", False)
    }
    assert paths == {
        "/query",
        "/jobs/{job_id}/trace",
        "/evals/latest",
        "/rewrites/{rewrite_id}/decision",
        "/evals/rerun-failures",
    }


def test_latest_evals_endpoint_shape():
    client = TestClient(app)
    response = client.get("/evals/latest")

    assert response.status_code == 200
    body = response.json()
    assert {"run_id", "run_at", "by_category", "by_dimension"} <= set(body)


def test_rewrite_decision_endpoint_rejects_pending_rewrite():
    run_all_cases()
    rewrite = load_rewrites()[-1]
    client = TestClient(app)

    response = client.post(f"/rewrites/{rewrite['id']}/decision", json={"decision": "reject", "notes": "API test"})

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_rerun_failures_endpoint_shape():
    client = TestClient(app)
    response = client.post("/evals/rerun-failures")

    assert response.status_code == 200
    assert {"run_id", "rerun_case_count", "summary"} <= set(response.json())
