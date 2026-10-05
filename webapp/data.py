"""Read-only data for the web UI: sample problems, saved runs and benchmark results.

Everything here reads files that the agent, the benchmark and the safety evaluation already
write (runs/*.json, results/*.json); the web layer never computes new numbers of its own.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from quantsolve import agent, tasks
from quantsolve.config import RESULTS_DIR, RUNS_DIR

# Presentation metadata for the sample problems (category, icon name, one-line blurb).
TASK_META: dict[str, dict[str, str]] = {
    "loan_prepay": {"short": "Home-loan prepayment", "category": "Loans", "icon": "home",
                    "blurb": "Rs 50 lakh home loan with a yearly Rs 1 lakh prepayment: months and "
                             "interest saved."},
    "sip_stepup": {"short": "Step-up SIP", "category": "Investing", "icon": "trend",
                   "blurb": "15-year monthly SIP with a 10% yearly step-up: future value and "
                            "wealth gained."},
    "income_tax": {"short": "Income tax 2024-25", "category": "Tax", "icon": "receipt",
                   "blurb": "New-regime income tax for three salaries, with rebate, marginal "
                            "relief and cess."},
    "projectile_drag": {"short": "Projectile with drag", "category": "Physics", "icon": "target",
                        "blurb": "Launch angle that maximises range when air drag is included."},
    "birthday": {"short": "Birthday paradox", "category": "Probability", "icon": "dice",
                 "blurb": "Exact group sizes for a shared birthday pair and a shared triple."},
    "eoq_discount": {"short": "Bulk-discount EOQ", "category": "Operations", "icon": "box",
                     "blurb": "Best order quantity when the supplier gives bulk discounts."},
    "compound_varying": {"short": "Changing interest rates", "category": "Interest", "icon": "percent",
                         "blurb": "Five years of changing rates and compounding, plus the "
                                  "equivalent annual rate."},
    "constrained_strings": {"short": "Counting codes", "category": "Counting", "icon": "hash",
                            "blurb": "Count 8-character codes with no two identical neighbours."},
}

ARM_LABELS = {"one_shot": "One-shot", "quantsolve": "Loop",
              "quantsolve+inject": "Loop + logic bug", "quantsolve+crash": "Loop + crash bug"}
RUN_ID_RE = re.compile(r"^[\w.-]{1,160}$")


def task_catalog() -> list[dict[str, Any]]:
    return [{"id": t.id, "title": t.title, "problem": t.problem, "keys": list(t.keys),
             **TASK_META.get(t.id, {"short": t.title, "category": "Problem", "icon": "hash", "blurb": t.title})}
            for t in tasks.TASKS.values()]


def task_id_for(problem: str) -> str | None:
    """A sample's id when `problem` is exactly that sample's text (so it can be scored)."""
    text = problem.strip()
    return next((t.id for t in tasks.TASKS.values() if t.problem.strip() == text), None)


# ------------------------------------------------------------------------- runs

def source_of(path: Path, runs_dir: Path = RUNS_DIR) -> str:
    if path.parent == runs_dir:
        return "mine"
    return "bench" if path.parent.name == "bench" else "archive"


def score_trace(trace: dict) -> dict | None:
    task = tasks.TASKS.get(trace.get("task_id") or "")
    return None if task is None else tasks.score(task, trace.get("result"))


def summarize_trace(trace: dict, source: str) -> dict[str, Any]:
    task = tasks.TASKS.get(trace.get("task_id") or "")
    first_line = (trace.get("task") or "").strip().splitlines()[0:1] or ["(empty task)"]
    title = task.title if task else first_line[0][:110]
    graded = score_trace(trace)
    usage = trace.get("usage") or {}
    return {
        "id": trace.get("run_id"),
        "source": source,
        "title": title,
        "task_id": trace.get("task_id"),
        "success": bool(trace.get("success")),
        "stopped": bool(trace.get("stopped")),
        "correct": None if graded is None else graded["correct"],
        "kinds": [a["observation"].get("kind", "ok") if not a["observation"].get("ok") else "ok"
                  for a in trace.get("attempts", [])],
        "inject": trace.get("inject"),
        "model": trace.get("model"),
        "created_at": trace.get("created_at"),
        "duration_s": trace.get("duration_s", 0.0),
        "cost_usd": usage.get("cost_usd", 0.0),
        "tokens": usage.get("total_tokens", 0),
    }


class HistoryIndex:
    """Run summaries, re-read only when a trace file's modification time changes."""

    def __init__(self, runs_dir: Path = RUNS_DIR) -> None:
        self.runs_dir = runs_dir
        self._cache: dict[Path, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def rows(self, scope: str = "mine") -> list[dict[str, Any]]:
        paths = agent.list_runs(self.runs_dir, include_subdirs=scope != "mine")
        out = []
        with self._lock:
            for path in paths:
                source = source_of(path, self.runs_dir)
                if scope not in ("all", source):
                    continue
                mtime = path.stat().st_mtime
                cached = self._cache.get(path)
                if cached is None or cached[0] != mtime:
                    try:
                        row = summarize_trace(json.loads(path.read_text()), source)
                    except (json.JSONDecodeError, KeyError, OSError):
                        continue
                    row["id"] = row["id"] or path.stem
                    cached = (mtime, row)
                    self._cache[path] = cached
                out.append(cached[1])
        return out


def find_run(run_id: str, runs_dir: Path = RUNS_DIR) -> Path | None:
    """Resolve a run id to a trace file inside runs_dir (never outside it)."""
    if not RUN_ID_RE.match(run_id) or run_id.startswith("."):
        return None
    root = runs_dir.resolve()
    for candidate in [runs_dir / f"{run_id}.json", *sorted(runs_dir.glob(f"*/{run_id}.json"))]:
        resolved = candidate.resolve()
        if resolved.is_file() and root in resolved.parents:
            return resolved
    return None


def load_run(run_id: str, runs_dir: Path = RUNS_DIR) -> dict | None:
    path = find_run(run_id, runs_dir)
    if path is None:
        return None
    trace = json.loads(path.read_text())
    trace["run_id"] = trace.get("run_id") or path.stem
    return {"trace": trace, "score": score_trace(trace),
            "source": source_of(path, runs_dir.resolve()),  # find_run returns a resolved path
            "task_title": (tasks.TASKS[trace["task_id"]].title
                           if trace.get("task_id") in tasks.TASKS else None)}


# ------------------------------------------------------------------------- results

def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def results(results_dir: Path = RESULTS_DIR) -> dict[str, Any]:
    bench = _read(results_dir / "benchmark.json")
    archive = _read(results_dir / "archive" / "benchmark_gpt-4o-mini.json")
    safety = _read(results_dir / "safety.json")
    out: dict[str, Any] = {"benchmark": None, "comparison": [], "safety": safety,
                           "arm_labels": ARM_LABELS}
    if bench:
        arms = list(bench["summary"])
        task_ids = bench["meta"]["tasks"]
        matrix = {t: {a: {"correct": 0, "runs": 0, "items": []} for a in arms} for t in task_ids}
        for row in bench["runs"]:
            cell = matrix.get(row["task_id"], {}).get(row["arm"])
            if cell is not None:
                cell["runs"] += 1
                cell["correct"] += int(bool(row["correct"]))
                if row.get("run_id"):
                    cell["items"].append({"id": row["run_id"], "correct": bool(row["correct"]),
                                          "attempts": row.get("attempts", 0)})
        out["benchmark"] = {
            "meta": bench["meta"], "summary": bench["summary"], "arms": arms,
            "tasks": [{"id": t, "title": tasks.TASKS[t].title if t in tasks.TASKS else t}
                      for t in task_ids],
            "matrix": matrix,
        }
        models = [(archive["meta"]["model"], archive)] if archive else []
        models.append((bench["meta"]["model"], bench))
        out["comparison"] = [
            {"model": name, "arms": {a: {"correct": s["correct"], "runs": s["runs"],
                                         "accuracy": s["accuracy"]}
                                     for a, s in data["summary"].items()}}
            for name, data in models]
    return out
