"""QuantSolve web server: a JSON API, a Server-Sent Events stream and the static front end.

    python3 web.py            # http://127.0.0.1:8503

API
  GET  /api/meta                    models, defaults, whether an API key is configured, team
  GET  /api/tasks                   the eight sample problems
  POST /api/runs                    start a solve job -> {"job_id"}
  GET  /api/runs/{job}              job status (done flag, number of events)
  GET  /api/runs/{job}/events       SSE stream of loop events (replays from ?after=N)
  POST /api/runs/{job}/stop         ask the loop to stop after the current step
  GET  /api/history?scope=...       saved runs: mine | bench | archive | all
  GET  /api/history/{run_id}        one saved trace plus its score against the reference
  GET  /api/results                 benchmark, model comparison and safety evaluation
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from quantsolve.config import RESULTS_DIR, RUNS_DIR, has_api_key, load_settings

from . import data
from .jobs import JobManager, TooManyJobs

STATIC = Path(__file__).resolve().parent / "static"
MODELS = ["gpt-4.1-mini", "gpt-4o-mini"]
TEAM = [{"name": "Deon Menezes", "roll": "16014223030", "batch": "B1"},
        {"name": "Aishwarya Gawali", "roll": "16014223007", "batch": "B1"}]
COURSE = "Generative AI Laboratory, Lab CA"
HEARTBEAT_S = 15.0


class NoCacheStatic(StaticFiles):
    """Static files that the browser always revalidates (cheap locally, never stale after edits)."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


class RunRequest(BaseModel):
    problem: str = Field(min_length=1, max_length=6000)
    model: str = MODELS[0]
    max_attempts: int = Field(default=5, ge=1, le=8)
    inject: Literal["none", "crash", "logic"] = "none"


def create_app(runs_dir: Path = RUNS_DIR, results_dir: Path = RESULTS_DIR,
               jobs: JobManager | None = None, key_check=has_api_key) -> FastAPI:
    app = FastAPI(title="QuantSolve", docs_url="/api/docs", redoc_url=None)
    manager = jobs or JobManager(runs_dir=runs_dir)
    history = data.HistoryIndex(runs_dir)
    app.state.jobs = manager

    # ---------------------------------------------------------------- reference data
    @app.get("/api/meta")
    def meta() -> dict:
        settings = load_settings()
        models = list(dict.fromkeys([settings.model, *MODELS]))
        return {"models": models, "default_model": settings.model,
                "max_attempts": settings.max_attempts, "timeout_s": settings.timeout_s,
                "api_key": key_check(), "team": TEAM, "course": COURSE}

    @app.get("/api/tasks")
    def task_list() -> list[dict]:
        return data.task_catalog()

    # ---------------------------------------------------------------- solve jobs
    @app.post("/api/runs", status_code=201)
    def start_run(req: RunRequest) -> dict:
        problem = req.problem.strip()
        if not problem:
            raise HTTPException(422, "Write a problem first.")
        if req.model not in MODELS and req.model != load_settings().model:
            raise HTTPException(422, f"Unknown model {req.model!r}.")
        if not key_check():
            raise HTTPException(503, "OPENAI_API_KEY is not set. Copy .env.example to .env, "
                                     "paste your key and restart the server.")
        settings = load_settings(model=req.model, max_attempts=req.max_attempts)
        inject = None if req.inject == "none" else req.inject
        try:
            job = manager.start(problem, settings, inject, data.task_id_for(problem))
        except TooManyJobs as exc:
            raise HTTPException(429, str(exc)) from exc
        return {"job_id": job.id}

    @app.get("/api/runs/{job_id}")
    def run_status(job_id: str) -> dict:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "No such run (the server may have restarted).")
        return {"job_id": job.id, "done": job.done, "events": len(job.since(0))}

    @app.get("/api/runs/{job_id}/events")
    async def run_events(job_id: str, request: Request, after: int = Query(0, ge=0)):
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "No such run (the server may have restarted).")
        last_id = request.headers.get("last-event-id")
        position = int(last_id) if last_id and last_id.isdigit() else after

        async def stream():
            nonlocal position
            idle = 0.0
            yield "retry: 2000\n\n"
            while True:
                fresh = job.since(position)
                for ev in fresh:
                    position = ev["id"]
                    yield (f"id: {ev['id']}\nevent: {ev['event']}\n"
                           f"data: {json.dumps({**ev['data'], '_t': ev['t']})}\n\n")
                if fresh:
                    idle = 0.0
                elif job.done:
                    yield "event: end\ndata: {}\n\n"
                    return
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.2)
                idle += 0.2
                if idle >= HEARTBEAT_S:
                    idle = 0.0
                    yield ": heartbeat\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/runs/{job_id}/stop")
    def stop_run(job_id: str) -> dict:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "No such run.")
        job.stop.set()
        return {"stopping": not job.done}

    # ---------------------------------------------------------------- saved runs and results
    @app.get("/api/history")
    def history_rows(scope: Literal["mine", "bench", "archive", "all"] = "mine") -> list[dict]:
        return history.rows(scope)

    @app.get("/api/history/{run_id}")
    def history_run(run_id: str) -> dict:
        found = data.load_run(run_id, runs_dir)
        if found is None:
            raise HTTPException(404, f"No saved run called {run_id!r}.")
        return found

    @app.get("/api/results")
    def results() -> dict:
        return data.results(results_dir)

    # ---------------------------------------------------------------- front end
    app.mount("/static", NoCacheStatic(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")

    return app


app = create_app()
