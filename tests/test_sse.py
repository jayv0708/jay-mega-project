import json

from fastapi.testclient import TestClient

from api.main import app


def test_query_stream_emits_job_and_completion():
    client = TestClient(app)
    with client.stream("POST", "/query", json={"query": "What is orchestration?"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
            if events and events[-1]["event_type"] == "JOB_COMPLETE":
                break

    assert events[0]["event_type"] == "HANDOFF"
    assert "job_id" in events[0]["data"]
    assert any(event["event_type"] == "TOKEN" for event in events)
    assert events[-1]["event_type"] == "JOB_COMPLETE"


def test_trace_endpoint_returns_memory_trace():
    client = TestClient(app)
    with client.stream("POST", "/query", json={"query": "Trace this"}) as response:
        first = None
        for line in response.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line.removeprefix("data: "))
                first = first or event
                if event["event_type"] == "JOB_COMPLETE":
                    break

    trace_response = client.get(f"/jobs/{first['data']['job_id']}/trace")
    assert trace_response.status_code == 200
    assert trace_response.json()["trace"]
