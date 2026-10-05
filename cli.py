"""QuantSolve command line.

    python3 cli.py solve "<problem>" [--inject crash|logic] [--max-attempts N]
    python3 cli.py tasks
    python3 cli.py run-task <id> [--inject crash|logic] [--max-attempts N]
    python3 cli.py bench [--tasks a,b] [--arms one_shot,quantsolve] [--repeats N] [--workers N]
    python3 cli.py bench --rescore      # recompute results from saved traces, no API calls
    python3 cli.py safety
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from quantsolve import agent, benchmark, safety_eval, tasks
from quantsolve.config import RESULTS_DIR, has_api_key, load_settings

console = Console()


def render_event(kind: str, payload: dict) -> None:
    """Print one loop event as a rich panel (Thought / Action / Observation / Reflection)."""
    n = payload.get("attempt")
    if kind == "attempt_start":
        console.rule(f"[bold]Attempt {n}")
    elif kind == "action":
        console.print(Panel(payload["thought"] or "(no thought)", title=f"Thought #{n}",
                            border_style="cyan"))
        if payload.get("injected"):
            console.print(Panel(payload["injected"], title="Injected fault (demo)",
                                border_style="yellow"))
        console.print(Panel(Syntax(payload["code"], "python", line_numbers=True,
                                   theme="monokai", word_wrap=True),
                            title=f"Action #{n}: code", border_style="blue"))
    elif kind == "observation":
        obs = payload["observation"]
        if obs["ok"]:
            body = f"RESULT = {json.dumps(obs['result'], indent=2)}"
            if obs.get("stdout"):
                body += f"\n\nstdout:\n{obs['stdout'].strip()[:800]}"
            console.print(Panel(body, title=f"Observation #{n}: ok ({obs['asserts']} self-checks "
                                f"passed, {obs['duration_s']:.2f}s)", border_style="green"))
        else:
            body = obs["message"] + (f"\n\n{obs['traceback']}" if obs.get("traceback") else "")
            console.print(Panel(body, title=f"Observation #{n}: {obs['kind'].upper()}",
                                border_style="red"))
    elif kind == "reflection":
        ref = payload["reflection"]
        body = (f"[bold]Diagnosis:[/bold] {ref['diagnosis']}\n[bold]Lesson:[/bold] "
                f"{ref['reflection']}\n[bold]Next plan:[/bold] {ref['next_plan']}")
        if payload.get("nudge"):
            body += f"\n[yellow]Loop guard:[/yellow] {payload['nudge']}"
        console.print(Panel(body, title=f"Reflection #{n} (stored in memory)",
                            border_style="magenta"))
    elif kind == "final":
        trace = payload["trace"]
        status = "verified" if trace["success"] else "not verified"
        console.print(Panel(trace["final_answer"], title=f"Final answer ({status})",
                            border_style="green" if trace["success"] else "red"))
        u = trace["usage"]
        console.print(f"[dim]attempts: {len(trace['attempts'])} | LLM calls: {u['calls']} | "
                      f"tokens: {u['prompt_tokens']} in + {u['completion_tokens']} out | "
                      f"cost: ${u['cost_usd']:.5f} | time: {trace['duration_s']}s[/dim]")


def run_solve(problem: str, args: argparse.Namespace, task_id: str | None = None) -> dict:
    if not has_api_key():
        raise SystemExit("OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in.")
    settings = load_settings(max_attempts=args.max_attempts)
    console.print(Panel(problem, title="Task", border_style="white"))
    trace = agent.solve(problem, settings=settings, inject=args.inject, task_id=task_id,
                        on_event=render_event)
    console.print(f"[dim]trace saved to {trace.path}[/dim]")
    return trace.to_dict()


def cmd_tasks(_: argparse.Namespace) -> None:
    table = Table(title="Sample problems")
    table.add_column("id", style="cyan")
    table.add_column("title")
    table.add_column("RESULT keys", style="dim")
    for t in tasks.TASKS.values():
        table.add_row(t.id, t.title, ", ".join(t.keys))
    console.print(table)


def cmd_run_task(args: argparse.Namespace) -> None:
    task = tasks.get_task(args.task_id)
    trace = run_solve(task.problem, args, task_id=task.id)
    graded = tasks.score(task, trace["result"])
    table = Table(title=f"Score vs hand-written reference: "
                        f"{'CORRECT' if graded['correct'] else 'WRONG'}")
    for col in ("key", "expected", "got", "ok"):
        table.add_column(col)
    for key, c in graded["checks"].items():
        table.add_row(key, str(c["expected"]), str(c["got"]), "yes" if c["ok"] else "[red]no")
    console.print(table)


def cmd_bench(args: argparse.Namespace) -> None:
    task_ids = args.tasks.split(",") if args.tasks else None
    arms = args.arms.split(",") if args.arms else None
    if args.rescore:
        report = benchmark.rescore(Path(args.rescore))
        print_bench_summary(report)
        return
    cases = benchmark.plan(task_ids, arms, args.repeats)
    console.print(f"Running {len(cases)} benchmark cases with {args.workers} workers ...")
    report = benchmark.run_benchmark(task_ids, arms, repeats=args.repeats, workers=args.workers,
                                     on_row=lambda r: console.print(
        f"  {r['task_id']:<20} {r['arm']:<18} #{r['repeat']} correct={r['correct']!s:<5} "
        f"attempts={r['attempts']} kinds={','.join(r['failure_kinds']) or '-'} "
        f"${r['cost_usd']:.5f} {r['error']}"))
    print_bench_summary(report)


def print_bench_summary(report: dict) -> None:
    table = Table(title="Benchmark summary")
    for col in ("arm", "runs", "accuracy", "verified", "verified but wrong", "avg attempts",
                "healed", "tokens", "cost $"):
        table.add_column(col)
    for arm, s in report["summary"].items():
        table.add_row(arm, str(s["runs"]), f"{s['accuracy']:.0%}", str(s["verified"]),
                      str(s["verified_but_wrong"]), f"{s['avg_attempts']:.2f}", str(s["healed"]),
                      str(s["tokens"]), f"{s['cost_usd']:.4f}")
    console.print(table)
    console.print("[dim]saved the benchmark JSON and CSV[/dim]")


def cmd_safety(_: argparse.Namespace) -> None:
    report = safety_eval.run_safety_eval()
    table = Table(title=f"Safety evaluation: {report['contained']}/{report['total']} contained")
    for col in ("attack", "gate", "outcome", "contained"):
        table.add_column(col)
    for r in report["attacks"]:
        table.add_row(r["title"], "on" if r["gate"] else "off", f"{r['kind']}: {(r['detail'] or r['message'])[:70]}",
                      "yes" if r["contained"] else "[red]NO")
    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="QuantSolve: self-verifying, self-healing solver")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_loop_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--inject", choices=["crash", "logic"], help="inject a bug into attempt 1")
        p.add_argument("--max-attempts", type=int, default=None)

    p = sub.add_parser("solve", help="solve a free-text problem")
    p.add_argument("problem")
    add_loop_options(p)
    p.set_defaults(func=lambda a: run_solve(a.problem, a))

    sub.add_parser("tasks", help="list sample problems").set_defaults(func=cmd_tasks)

    p = sub.add_parser("run-task", help="solve a sample problem and score it")
    p.add_argument("task_id", choices=list(tasks.TASKS))
    add_loop_options(p)
    p.set_defaults(func=cmd_run_task)

    p = sub.add_parser("bench", help="run the benchmark (uses the API)")
    p.add_argument("--tasks", help="comma-separated task ids (default: all)")
    p.add_argument("--arms", help=f"comma-separated arms from {', '.join(benchmark.ARMS)}")
    p.add_argument("--repeats", type=int, default=1, help="run every case this many times")
    p.add_argument("--workers", type=int, default=4, help="cases run in parallel")
    p.add_argument("--rescore", nargs="?", const=str(RESULTS_DIR / "benchmark.json"),
                   metavar="BENCHMARK_JSON",
                   help="recompute scores and summary from saved traces (no API calls); "
                        "default results/benchmark.json")
    p.set_defaults(func=cmd_bench)

    sub.add_parser("safety", help="run the sandbox safety evaluation (offline)") \
        .set_defaults(func=cmd_safety)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
