"""Background solve jobs for the web UI.

Each job runs `agent.solve` in its own thread and records every loop event in an append-only
log. The SSE endpoint replays that log from any position, so a browser that reconnects (or a
second tab) sees the whole run. A job's stop flag is passed to the agent as `should_stop`.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from quantsolve import agent
from quantsolve.config import RUNS_DIR, Settings

from . import data

MAX_ACTIVE_JOBS = 3
KEEP_FINISHED_JOBS = 50


class TooManyJobs(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    problem: str
    created: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    stop: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def push(self, kind: str, payload: dict[str, Any]) -> None:
        with self.lock:
            self.events.append({"id": len(self.events) + 1, "event": kind, "data": payload,
                                "t": round(time.time() - self.created, 2)})

    def since(self, after: int) -> list[dict[str, Any]]:
        with self.lock:
            return self.events[after:]


class JobManager:
    def __init__(self, runs_dir: Path = RUNS_DIR,
                 solve: Callable[..., agent.RunTrace] | None = None) -> None:
        self.runs_dir = runs_dir
        self.solve = solve or agent.solve
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def active(self) -> int:
        with self.lock:
            return sum(not j.done for j in self.jobs.values())

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def start(self, problem: str, settings: Settings, inject: str | None,
              task_id: str | None) -> Job:
        with self.lock:
            if sum(not j.done for j in self.jobs.values()) >= MAX_ACTIVE_JOBS:
                raise TooManyJobs(f"{MAX_ACTIVE_JOBS} runs are already in progress")
            job = Job(id=uuid.uuid4().hex[:12], problem=problem)
            self.jobs[job.id] = job
            self._forget_old()
        job.push("started", {"model": settings.model, "max_attempts": settings.max_attempts,
                             "inject": inject, "task_id": task_id})
        threading.Thread(target=self._work, args=(job, settings, inject, task_id),
                         name=f"quantsolve-job-{job.id}", daemon=True).start()
        return job

    def _work(self, job: Job, settings: Settings, inject: str | None,
              task_id: str | None) -> None:
        def on_event(kind: str, payload: dict[str, Any]) -> None:
            if kind == "final":  # attach the reference score so the UI can show it at once
                payload = {**payload, "score": data.score_trace(payload["trace"])}
            job.push(kind, payload)

        try:
            self.solve(job.problem, settings=settings, inject=inject, task_id=task_id,
                       on_event=on_event, should_stop=job.stop.is_set, runs_dir=self.runs_dir)
        except Exception as exc:  # API, network or unexpected errors end the job visibly
            job.push("error", {"message": friendly_error(exc)})
        finally:
            job.done = True

    def _forget_old(self) -> None:
        finished = sorted((j for j in self.jobs.values() if j.done), key=lambda j: j.created)
        for old in finished[:-KEEP_FINISHED_JOBS]:
            self.jobs.pop(old.id, None)


def friendly_error(exc: Exception) -> str:
    name = type(exc).__name__
    text = str(exc).strip().splitlines()[0][:300] if str(exc).strip() else ""
    if "AuthenticationError" in name:
        return "The OpenAI API rejected the key in .env (authentication error)."
    if "RateLimit" in name:
        return "The OpenAI API rate limit was hit. Wait a few seconds and try again."
    if "Connection" in name or "Timeout" in name:
        return "Could not reach the OpenAI API. Check the internet connection and try again."
    return f"{name}: {text}" if text else name
