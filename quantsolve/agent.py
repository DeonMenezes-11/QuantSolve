"""The ReAct + Reflexion loop: Thought -> Action (code) -> Observation -> Reflection -> retry.

    memory = []                                    # Reflexion episodic memory
    for attempt in 1..max_attempts:
        thought, code = solve(task, last_code, last_obs, memory)    # Thought + Action
        if attempt == 1 and inject: code = faults.mutate(code, inject)
        obs = sandbox.run(code)                                     # Observation
        if obs.ok: break
        memory.append(reflect(task, code, obs, memory))             # Reflexion
    answer = summarize(task, obs.result)
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import faults, llm, prompts, sandbox
from .config import PROJECT_ROOT, RUNS_DIR, Settings, load_settings
from .sandbox import ExecutionResult

EventCallback = Callable[[str, dict[str, Any]], None]

NUDGE_SAME_CODE = ("You submitted code that is identical to an earlier attempt. That approach "
                   "already failed; try a different one.")
NUDGE_SAME_ERROR = ("The same error ({sig}) happened again. You repeated the same approach; "
                    "rethink the method instead of making a cosmetic change.")
NUDGE_ASSERT_HINT = (" When the same check keeps failing, one of its two sides is wrong: evaluate "
                     "both methods on a tiny case (e.g. 1-2 periods) where the answer is obvious, "
                     "print the values, and fix whichever side disagrees with it.")


@dataclass
class Attempt:
    number: int
    thought: str
    code: str                           # the code that was executed
    observation: dict
    llm_code: str | None = None         # the model's original code if a fault was injected
    injected: str | None = None         # description of the injected fault
    reflection: dict | None = None
    nudge: str | None = None            # loop-guard warning raised after this attempt


@dataclass
class RunTrace:
    run_id: str
    task: str
    task_id: str | None
    model: str
    inject: str | None
    max_attempts: int
    created_at: str
    attempts: list[Attempt] = field(default_factory=list)
    success: bool = False
    result: dict | None = None
    final_answer: str = ""
    usage: dict = field(default_factory=dict)
    duration_s: float = 0.0
    path: str | None = None
    stopped: bool = False               # ended early because should_stop() returned True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ LLM steps

def _strip_fences(code: str) -> str:
    match = re.search(r"```(?:python)?\s*\n(.*?)```", code, re.S)
    return (match.group(1) if match else code).strip() + "\n"


def solve_step(task: str, settings: Settings, usage: llm.Usage, previous_code: str | None = None,
               observation: dict | None = None, memory: list[dict] | None = None,
               nudge: str | None = None) -> tuple[str, str]:
    """Thought + Action: ask the model for a plan and a complete program."""
    user = prompts.solve_user(task, previous_code, observation, memory, nudge)
    temperature = settings.nudge_temperature if nudge else None  # more variety after a repeat
    data = llm.chat_json(prompts.SOLVE_SYSTEM, user, settings, usage, temperature=temperature)
    return str(data.get("thought", "")).strip(), _strip_fences(str(data.get("code", "")))


def reflect_step(task: str, code: str, observation: dict, memory: list[dict],
                 settings: Settings, usage: llm.Usage) -> dict:
    """Reflexion: turn a failed observation into a short verbal lesson."""
    user = prompts.reflect_user(task, code, observation, memory)
    data = llm.chat_json(prompts.REFLECT_SYSTEM, user, settings, usage,
                         temperature=settings.reflect_temperature)
    return {k: str(data.get(k, "")).strip() for k in ("diagnosis", "reflection", "next_plan")}


def summarize_step(task: str, result: dict, settings: Settings, usage: llm.Usage) -> str:
    data = llm.chat_json(prompts.SUMMARIZE_SYSTEM, prompts.summarize_user(task, result),
                         settings, usage)
    return str(data.get("answer", "")).strip() or json.dumps(result)


# ------------------------------------------------------------------ loop guard

def code_fingerprint(code: str) -> str:
    """Hash of the normalised AST, so whitespace/comment-only changes count as a repeat."""
    try:
        text = ast.dump(ast.parse(code))
    except SyntaxError:
        text = code.strip()
    return hashlib.sha1(text.encode()).hexdigest()


def error_signature(obs: ExecutionResult, code: str) -> tuple:
    """(kind, exception type, failing line). The line is compared by its source text so that
    edits elsewhere that shift line numbers still count as the same error."""
    lines = code.splitlines()
    where = lines[obs.line - 1].strip() if obs.line and 0 < obs.line <= len(lines) else obs.line
    return (obs.kind, obs.exc_type, where)


# ------------------------------------------------------------------ main loop

def solve(task: str, *, settings: Settings | None = None, inject: str | None = None,
          task_id: str | None = None, on_event: EventCallback | None = None,
          save: bool = True, runs_dir: Path = RUNS_DIR, summarize: bool = True,
          should_stop: Callable[[], bool] | None = None) -> RunTrace:
    """Run the self-healing loop on `task` and return the full trace.

    `should_stop` is polled before each attempt and before each reflection; the web UI uses
    it for its Stop button.
    """
    settings = settings or load_settings()
    emit = on_event or (lambda kind, payload: None)
    stop_requested = should_stop or (lambda: False)
    usage = llm.Usage()
    started = time.perf_counter()
    trace = RunTrace(run_id="", task=task, task_id=task_id, model=settings.model, inject=inject,
                     max_attempts=settings.max_attempts,
                     created_at=datetime.now().isoformat(timespec="seconds"))
    memory: list[dict] = []
    seen_code: set[str] = set()
    seen_errors: set[tuple] = set()
    last_code: str | None = None
    last_obs: dict | None = None
    nudge: str | None = None
    obs = ExecutionResult(False, "contract", "no attempt was made")

    for number in range(1, settings.max_attempts + 1):
        if stop_requested():
            trace.stopped = True
            break
        emit("attempt_start", {"attempt": number})
        thought, code = solve_step(task, settings, usage, last_code, last_obs, memory, nudge)
        llm_code, injected = None, None
        if number == 1 and inject:
            llm_code = code
            code, injected = faults.mutate(code, inject)
        emit("action", {"attempt": number, "thought": thought, "code": code,
                        "llm_code": llm_code, "injected": injected})

        if code.strip():
            obs = sandbox.run(code, timeout_s=settings.timeout_s)
        else:
            obs = ExecutionResult(False, "contract", "The response did not contain any code.")
        attempt = Attempt(number, thought, code, obs.to_dict(), llm_code, injected)
        trace.attempts.append(attempt)
        emit("observation", {"attempt": number, "observation": attempt.observation,
                             "usage": usage.to_dict()})
        if obs.ok:
            break

        # Loop guard: identical code or an identical error signature -> nudge next prompt.
        fingerprint, signature = code_fingerprint(code), error_signature(obs, code)
        nudge = None
        if fingerprint in seen_code:
            nudge = NUDGE_SAME_CODE
        elif signature in seen_errors:
            nudge = NUDGE_SAME_ERROR.format(sig=f"{obs.kind} {obs.exc_type or ''} line {obs.line}")
            if obs.kind == "assertion":
                nudge += NUDGE_ASSERT_HINT
        seen_code.add(fingerprint)
        seen_errors.add(signature)
        attempt.nudge = nudge

        if stop_requested():
            trace.stopped = True
            break
        if number < settings.max_attempts:  # no point reflecting after the last attempt
            reflection = reflect_step(task, code, attempt.observation, memory, settings, usage)
            reflection["attempt"] = number
            attempt.reflection = reflection
            memory.append(reflection)
            emit("reflection", {"attempt": number, "reflection": reflection, "nudge": nudge,
                                "usage": usage.to_dict()})
        last_code, last_obs = code, attempt.observation

    trace.success = obs.ok
    trace.result = obs.result if obs.ok else None
    if obs.ok:
        if summarize:
            emit("summarizing", {"attempt": len(trace.attempts)})
        trace.final_answer = (summarize_step(task, obs.result or {}, settings, usage)
                              if summarize else json.dumps(obs.result))
    elif trace.stopped:
        trace.final_answer = f"Stopped by user after {len(trace.attempts)} attempt(s)."
    else:
        trace.final_answer = (f"No verified answer after {len(trace.attempts)} attempt(s). "
                              f"Last failure ({obs.kind}): {(obs.message.splitlines() or [''])[0][:300]}")
    trace.usage = usage.to_dict()
    trace.duration_s = round(time.perf_counter() - started, 2)
    if save:
        save_trace(trace, runs_dir)
    emit("final", {"trace": trace.to_dict()})
    return trace


# ------------------------------------------------------------------ persistence

def _slug(text: str, limit: int = 40) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-").split("-")
    return "-".join(words[:6])[:limit] or "task"


def _display_path(path: Path) -> str:
    """Project-relative path for the trace file (keeps machine-specific folders out of traces)."""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path)


def save_trace(trace: RunTrace, runs_dir: Path = RUNS_DIR) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y%m%d-%H%M%S}_{trace.task_id or _slug(trace.task)}"
    if trace.inject:
        stem += f"_inject-{trace.inject}"
    path, n = runs_dir / f"{stem}.json", 2
    while True:  # exclusive create: safe when several runs finish in the same second
        try:
            with open(path, "x"):
                break
        except FileExistsError:
            path, n = runs_dir / f"{stem}-{n}.json", n + 1
    trace.run_id = path.stem
    trace.path = _display_path(path)
    path.write_text(json.dumps(trace.to_dict(), indent=2))
    return path


def list_runs(runs_dir: Path = RUNS_DIR, include_subdirs: bool = False) -> list[Path]:
    """Saved traces in runs/, optionally also in its sub-folders (bench/, archive_*/)."""
    paths = list(runs_dir.glob("*.json"))
    if include_subdirs:
        paths += list(runs_dir.glob("*/*.json"))
    return sorted(paths, key=lambda p: p.name, reverse=True)


def load_trace(run: str | Path, runs_dir: Path = RUNS_DIR) -> dict:
    """Load a saved trace by path or by run id (file stem, searched in runs/ and sub-folders)."""
    path = Path(run)
    if not path.exists():
        candidates = [runs_dir / f"{run}.json", runs_dir / "bench" / f"{run}.json",
                      *sorted(runs_dir.glob(f"*/{run}.json"))]
        path = next((c for c in candidates if c.exists()), candidates[0])
    return json.loads(path.read_text())
