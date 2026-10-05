"""Web API tests (FastAPI TestClient + the scripted fake LLM; no network)."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from quantsolve import agent, tasks
from quantsolve.config import Settings
from tests.test_agent import CRASHING, GOOD, FakeLLM
from webapp import data
from webapp.jobs import MAX_ACTIVE_JOBS, JobManager
from webapp.server import create_app


@pytest.fixture
def runs_dir(tmp_path):
    path = tmp_path / "runs"
    path.mkdir()
    return path


@pytest.fixture
def results_dir(tmp_path):
    path = tmp_path / "results"
    (path / "archive").mkdir(parents=True)
    summary = {"runs": 2, "correct": 1, "accuracy": 0.5, "verified": 2, "verified_but_wrong": 1,
               "avg_attempts": 1.5, "healed": 1, "inject_outcomes": {}, "failure_kinds": {},
               "tokens": 100, "cost_usd": 0.001, "avg_duration_s": 1.0}
    bench = {"meta": {"created_at": "2026-10-04T23:53:57", "model": "gpt-4.1-mini", "max_attempts": 5,
                      "timeout_s": 10.0, "repeats": 2, "tasks": ["income_tax"], "crash_tasks": []},
             "summary": {"one_shot": summary, "quantsolve": {**summary, "correct": 2, "accuracy": 1.0}},
             "runs": [{"task_id": "income_tax", "arm": "quantsolve", "correct": True, "attempts": 2, "run_id": "r1"},
                      {"task_id": "income_tax", "arm": "quantsolve", "correct": True, "attempts": 1, "run_id": "r2"}]}
    (path / "benchmark.json").write_text(json.dumps(bench))
    (path / "archive" / "benchmark_gpt-4o-mini.json").write_text(json.dumps({**bench, "meta": {**bench["meta"], "model": "gpt-4o-mini"}}))
    (path / "safety.json").write_text(json.dumps({"contained": 1, "total": 1, "attacks": []}))
    return path


@pytest.fixture
def client(runs_dir, results_dir):
    return TestClient(create_app(runs_dir=runs_dir, results_dir=results_dir, key_check=lambda: True))


def sse_events(client, job_id, timeout=60):
    """Read a job's SSE stream to the end and return [(event, data)]."""
    events, kind = [], None
    deadline = time.time() + timeout
    with client.stream("GET", f"/api/runs/{job_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if time.time() > deadline:
                raise TimeoutError("stream did not end")
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: ") and kind:
                events.append((kind, json.loads(line[6:])))
                if kind == "end":
                    break
    return events


def save_sample_trace(runs_dir, success=True):
    task = tasks.TASKS["income_tax"]
    trace = agent.RunTrace(run_id="", task=task.problem, task_id=task.id, model="gpt-4.1-mini", inject="crash",
                           max_attempts=5, created_at="2026-10-05T10:00:00", success=success,
                           result=tasks.reference_answer(task.id) if success else None, final_answer="Answer.")
    trace.attempts.append(agent.Attempt(1, "plan", "x = 1", {"ok": False, "kind": "runtime", "message": "NameError"}))
    trace.attempts.append(agent.Attempt(2, "plan", "x = 2", {"ok": True, "kind": "ok", "asserts": 2}))
    return agent.save_trace(trace, runs_dir)


# ------------------------------------------------------------------ reference data

def test_meta_and_tasks(client):
    meta = client.get("/api/meta").json()
    assert "gpt-4.1-mini" in meta["models"] and meta["api_key"] is True
    assert [m["name"] for m in meta["team"]] == ["Deon Menezes", "Aishwarya Gawali"]
    catalog = client.get("/api/tasks").json()
    assert len(catalog) == len(tasks.TASKS)
    assert all({"id", "title", "short", "problem", "keys", "category", "icon", "blurb"} <= set(t) for t in catalog)


def test_sample_problem_is_recognised_for_scoring():
    task = tasks.TASKS["sip_stepup"]
    assert data.task_id_for("  " + task.problem + "\n") == "sip_stepup"
    assert data.task_id_for(task.problem + " (edited)") is None


def test_front_end_is_served(client):
    page = client.get("/")
    assert page.status_code == 200 and "QuantSolve" in page.text
    script = client.get("/static/js/app.js")
    assert script.status_code == 200 and script.headers["cache-control"] == "no-cache"


# ------------------------------------------------------------------ history and results

def test_history_lists_and_scores_saved_runs(client, runs_dir):
    path = save_sample_trace(runs_dir)
    rows = client.get("/api/history?scope=mine").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == path.stem and row["success"] and row["correct"] is True
    assert row["kinds"] == ["runtime", "ok"] and row["inject"] == "crash"
    detail = client.get(f"/api/history/{path.stem}").json()
    assert detail["trace"]["task_id"] == "income_tax" and detail["score"]["correct"] is True
    assert detail["task_title"] == tasks.TASKS["income_tax"].title and detail["source"] == "mine"


def test_history_scopes_include_sub_folders(client, runs_dir):
    (runs_dir / "bench").mkdir()
    save_sample_trace(runs_dir / "bench", success=False)
    assert client.get("/api/history?scope=mine").json() == []
    bench_rows = client.get("/api/history?scope=bench").json()
    assert len(bench_rows) == 1 and bench_rows[0]["source"] == "bench" and bench_rows[0]["correct"] is False
    assert len(client.get("/api/history?scope=all").json()) == 1
    assert client.get("/api/history?scope=nonsense").status_code == 422


@pytest.mark.parametrize("bad", ["..%2F..%2Fetc%2Fpasswd", ".hidden", "a b", "x" * 200])
def test_history_rejects_unsafe_or_unknown_ids(client, bad):
    assert client.get(f"/api/history/{bad}").status_code == 404


def test_find_run_never_leaves_the_runs_dir(runs_dir, tmp_path):
    (tmp_path / "secret.json").write_text("{}")
    assert data.find_run("../secret", runs_dir) is None
    assert data.find_run("secret", runs_dir) is None


def test_results_combine_benchmark_archive_and_safety(client):
    res = client.get("/api/results").json()
    cell = res["benchmark"]["matrix"]["income_tax"]["quantsolve"]
    assert cell["correct"] == 2 and cell["runs"] == 2 and [i["id"] for i in cell["items"]] == ["r1", "r2"]
    assert [m["model"] for m in res["comparison"]] == ["gpt-4o-mini", "gpt-4.1-mini"]
    assert res["safety"]["contained"] == 1 and res["arm_labels"]["quantsolve"] == "Loop"


# ------------------------------------------------------------------ solve jobs

@pytest.mark.parametrize("body", [
    {"problem": ""}, {"problem": "   "}, {"problem": "x", "model": "gpt-99"},
    {"problem": "x", "max_attempts": 0}, {"problem": "x", "max_attempts": 9},
    {"problem": "x", "inject": "chaos"}, {"problem": "x" * 6001},
])
def test_run_request_validation(client, body):
    assert client.post("/api/runs", json=body).status_code == 422


def test_run_needs_an_api_key(runs_dir, results_dir):
    no_key = TestClient(create_app(runs_dir=runs_dir, results_dir=results_dir, key_check=lambda: False))
    response = no_key.post("/api/runs", json={"problem": "Add 1 and 1."})
    assert response.status_code == 503 and "OPENAI_API_KEY" in response.json()["detail"]


def test_full_job_streams_every_step_and_saves_the_trace(client, runs_dir, monkeypatch):
    monkeypatch.setattr(agent.llm, "chat_json", FakeLLM([CRASHING, GOOD]))
    monkeypatch.setattr("webapp.server.load_settings", lambda **kw: Settings(**{"timeout_s": 5, **kw}))
    job_id = client.post("/api/runs", json={"problem": "Add the numbers 1..10.", "max_attempts": 3}).json()["job_id"]
    events = sse_events(client, job_id)
    kinds = [k for k, _ in events]
    assert kinds[:6] == ["started", "attempt_start", "action", "observation", "reflection", "attempt_start"]
    assert kinds[-3:] == ["summarizing", "final", "end"]
    first_obs = next(d for k, d in events if k == "observation")
    assert first_obs["observation"]["exc_type"] == "NameError" and first_obs["usage"]["calls"] >= 1
    final = events[-2][1]
    assert final["trace"]["success"] and final["trace"]["result"] == {"total": 55} and final["score"] is None
    saved = list(runs_dir.glob("*.json"))
    assert len(saved) == 1 and json.loads(saved[0].read_text())["run_id"] == final["trace"]["run_id"]
    # the log replays from the start for a late subscriber (page refresh)
    assert [k for k, _ in sse_events(client, job_id)] == kinds
    assert client.get(f"/api/runs/{job_id}").json()["done"] is True


def test_stop_ends_the_run_early(client, runs_dir, monkeypatch):
    fake = FakeLLM([CRASHING])

    def slow(*args, **kwargs):
        time.sleep(0.4)
        return fake(*args, **kwargs)

    monkeypatch.setattr(agent.llm, "chat_json", slow)
    job_id = client.post("/api/runs", json={"problem": "Add the numbers 1..10.", "max_attempts": 5}).json()["job_id"]
    assert client.post(f"/api/runs/{job_id}/stop").json() == {"stopping": True}
    final = dict(sse_events(client, job_id))["final"]["trace"]
    assert final["stopped"] is True and not final["success"]
    assert len(final["attempts"]) <= 1 and final["final_answer"].startswith("Stopped by user")


def test_unknown_job_is_404(client):
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/events").status_code == 404
    assert client.post("/api/runs/nope/stop").status_code == 404


def test_too_many_concurrent_jobs_is_429(runs_dir, results_dir):
    release = threading.Event()

    def blocking_solve(problem, **kwargs):
        release.wait(10)
        raise RuntimeError("released")

    manager = JobManager(runs_dir=runs_dir, solve=blocking_solve)
    busy = TestClient(create_app(runs_dir=runs_dir, results_dir=results_dir, jobs=manager, key_check=lambda: True))
    try:
        for _ in range(MAX_ACTIVE_JOBS):
            assert busy.post("/api/runs", json={"problem": "x"}).status_code == 201
        assert busy.post("/api/runs", json={"problem": "x"}).status_code == 429
    finally:
        release.set()


def test_api_errors_become_an_error_event(client, monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr(agent.llm, "chat_json", broken)
    job_id = client.post("/api/runs", json={"problem": "x"}).json()["job_id"]
    events = dict(sse_events(client, job_id))
    assert "Could not reach the OpenAI API" in events["error"]["message"]
