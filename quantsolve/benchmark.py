"""Benchmark: one-shot vs the self-healing loop vs the loop with an injected bug.

Arms
- one_shot           max_attempts = 1 (generate once, no healing)
- quantsolve         the full loop
- quantsolve+inject  the loop with a `logic` fault injected into attempt 1
- quantsolve+crash   the loop with a `crash` fault on attempt 1 (a subset of tasks)

For injected-fault runs the model's original (un-mutated) attempt-1 program is re-run offline,
so a failure can be attributed to the injected fault (`caught`) rather than to a bug the model
wrote itself (`original_failed`); `silent` means the fault changed the numbers and still passed
the self-checks, `benign` means it changed nothing that mattered.

Each (task, arm) case can be repeated; cases run in a small thread pool (the work is
I/O-bound API calls plus sandbox child processes). Writes results/benchmark.json and
results/benchmark.csv; traces go to runs/bench/.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import agent, sandbox, tasks
from .config import RESULTS_DIR, RUNS_DIR, Settings, load_settings

ARMS: dict[str, dict] = {
    "one_shot": {"max_attempts": 1, "inject": None},
    "quantsolve": {"max_attempts": None, "inject": None},
    "quantsolve+inject": {"max_attempts": None, "inject": "logic"},
    "quantsolve+crash": {"max_attempts": None, "inject": "crash"},
}
CRASH_TASKS = ("loan_prepay", "income_tax", "eoq_discount")
CSV_FIELDS = ["task_id", "arm", "repeat", "correct", "keys_correct", "keys_total", "verified", "attempts",
              "first_kind", "failure_kinds", "healed", "inject_applied", "inject_detected", "inject_outcome",
              "tokens", "cost_usd", "duration_s", "run_id", "error"]


def injection_outcome(trace: dict, timeout_s: float = 10.0) -> str | None:
    """Attribute the attempt-1 outcome of an injected run: caught / silent / benign / ..."""
    if not trace.get("inject"):
        return None
    first = trace["attempts"][0]
    if not first.get("llm_code") or first["code"] == first["llm_code"]:
        return "not_applied"
    original = sandbox.run(first["llm_code"], timeout_s=timeout_s)
    if not original.ok:
        return "original_failed"          # the model's own bug; cannot credit the fault
    if not first["observation"]["ok"]:
        return "caught"                   # the fault made the program fail its checks / crash
    if first["observation"]["result"] != original.result:
        return "silent"                   # wrong numbers passed the self-checks
    return "benign"


def run_case(task: tasks.Task, arm: str, settings: Settings, repeat: int = 1) -> dict:
    spec = ARMS[arm]
    arm_settings = replace(settings, max_attempts=spec["max_attempts"] or settings.max_attempts)
    row = {"task_id": task.id, "arm": arm, "repeat": repeat, "inject": spec["inject"]}
    try:
        trace = agent.solve(task.problem, settings=arm_settings, inject=spec["inject"],
                            task_id=task.id, runs_dir=RUNS_DIR / "bench")
    except Exception as exc:  # an API failure should not kill the whole benchmark
        return {**row, "correct": False, "keys_correct": 0, "keys_total": len(task.keys),
                "verified": False, "attempts": 0, "first_kind": "error", "failure_kinds": [],
                "healed": False, "inject_applied": False, "inject_detected": False, "tokens": 0,
                "cost_usd": 0.0, "duration_s": 0.0, "run_id": "", "error": str(exc)[:300]}
    graded = tasks.score(task, trace.result)
    observations = [a.observation for a in trace.attempts]
    first = trace.attempts[0]
    return {
        **row,
        "correct": graded["correct"],
        "keys_correct": sum(c["ok"] for c in graded["checks"].values()),
        "keys_total": len(graded["checks"]),
        "verified": trace.success,                       # final program passed its self-checks
        "attempts": len(trace.attempts),
        "first_kind": observations[0]["kind"],
        "failure_kinds": [o["kind"] for o in observations if not o["ok"]],
        "healed": (not observations[0]["ok"]) and trace.success,
        "inject_applied": bool(first.injected and not first.injected.startswith("no ")),
        "inject_detected": bool(spec["inject"]) and not observations[0]["ok"],
        "inject_outcome": injection_outcome(trace.to_dict(), settings.timeout_s),
        "tokens": trace.usage.get("total_tokens", 0),
        "cost_usd": trace.usage.get("cost_usd", 0.0),
        "duration_s": trace.duration_s,
        "run_id": trace.run_id,
        "checks": graded["checks"],
        "error": "",
    }


def summarize(rows: list[dict]) -> dict[str, dict]:
    summary = {}
    for arm in ARMS:
        group = [r for r in rows if r["arm"] == arm]
        if not group:
            continue
        n = len(group)
        summary[arm] = {
            "runs": n,
            "correct": sum(r["correct"] for r in group),
            "accuracy": round(sum(r["correct"] for r in group) / n, 3),
            "verified": sum(r["verified"] for r in group),
            "verified_but_wrong": sum(r["verified"] and not r["correct"] for r in group),
            "avg_attempts": round(sum(r["attempts"] for r in group) / n, 2),
            "healed": sum(r["healed"] for r in group),
            "inject_applied": sum(r["inject_applied"] for r in group),
            "inject_detected": sum(r["inject_detected"] for r in group),
            "inject_outcomes": dict(Counter(r["inject_outcome"] for r in group
                                            if r.get("inject_outcome"))),
            "failure_kinds": dict(Counter(k for r in group for k in r["failure_kinds"])),
            "tokens": sum(r["tokens"] for r in group),
            "cost_usd": round(sum(r["cost_usd"] for r in group), 5),
            "avg_duration_s": round(sum(r["duration_s"] for r in group) / n, 2),
            "errors": sum(bool(r["error"]) for r in group),
        }
    return summary


def plan(task_ids: list[str] | None = None, arms: list[str] | None = None,
         repeats: int = 1) -> list[tuple[str, str, int]]:
    cases = []
    for repeat in range(1, repeats + 1):
        for task_id in task_ids or list(tasks.TASKS):
            for arm in arms or list(ARMS):
                if arm == "quantsolve+crash" and task_id not in CRASH_TASKS:
                    continue
                cases.append((task_id, arm, repeat))
    return cases


def run_benchmark(task_ids: list[str] | None = None, arms: list[str] | None = None,
                  settings: Settings | None = None, repeats: int = 1, workers: int = 4,
                  on_row: Callable[[dict], None] | None = None) -> dict:
    settings = settings or load_settings()
    cases = plan(task_ids, arms, repeats)
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_case, tasks.get_task(t), arm, settings, r): (t, arm, r)
                   for t, arm, r in cases}
        for future in as_completed(futures):
            rows.append(future.result())
            if on_row:
                on_row(rows[-1])
    order = {case: i for i, case in enumerate(cases)}
    rows.sort(key=lambda r: order[(r["task_id"], r["arm"], r["repeat"])])
    report = {
        "meta": {"created_at": datetime.now().isoformat(timespec="seconds"),
                 "model": settings.model, "max_attempts": settings.max_attempts,
                 "timeout_s": settings.timeout_s, "repeats": repeats,
                 "tasks": sorted({r["task_id"] for r in rows}),
                 "crash_tasks": list(CRASH_TASKS)},
        "summary": summarize(rows),
        "runs": rows,
    }
    save(report)
    return report


def rescore(path: Path = RESULTS_DIR / "benchmark.json") -> dict:
    """Recompute scores, injection outcomes and the summary from saved traces (no API calls).

    Traces are found by run id in runs/ and its sub-folders, so archived benchmarks work too."""
    report = json.loads(path.read_text())
    for row in report["runs"]:
        if not row.get("run_id"):
            continue
        trace = agent.load_trace(row["run_id"], RUNS_DIR)
        graded = tasks.score(tasks.get_task(row["task_id"]), trace["result"])
        row.update(correct=graded["correct"], checks=graded["checks"],
                   keys_correct=sum(c["ok"] for c in graded["checks"].values()),
                   inject_outcome=injection_outcome(trace, report["meta"]["timeout_s"]))
    report["summary"] = summarize(report["runs"])
    save(report, path)
    return report


def save(report: dict, path: Path = RESULTS_DIR / "benchmark.json") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    with open(path.with_suffix(".csv"), "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in report["runs"]:
            writer.writerow({**row, "failure_kinds": " ".join(row["failure_kinds"])})


if __name__ == "__main__":
    out = run_benchmark(on_row=lambda r: print(r["task_id"], r["arm"], r["correct"], r["attempts"]))
    print(json.dumps(out["summary"], indent=2))
