"""Build the PDF lab report from the project's real outputs.

    python3 report/build_report.py [--showcase <run id>]

Reads results/benchmark.json, results/safety.json and a saved run from runs/ (the showcase:
an injected-bug run that healed and is correct), draws the figures with matplotlib and lays
out the PDF with reportlab. No result number is typed into the prose by hand.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "report"))

import figures  # noqa: E402
from quantsolve import benchmark, llm, sandbox, tasks  # noqa: E402
from quantsolve.sandbox import ALLOWED_MODULES  # noqa: E402

FIG = ROOT / "report" / "figures"
OUT = ROOT / "report" / "QuantSolve_Report_Deon_Menezes_Aishwarya_Gawali.pdf"
NAVY = colors.HexColor("#1f3a5f")
LIGHT = colors.HexColor("#eef3f9")
CODE_BG = colors.HexColor("#f6f6f4")
RULE = colors.HexColor("#c9d3df")
TEXT_W = A4[0] - 2 * 2.2 * cm

REPO = "https://github.com/DeonMenezes-11/QuantSolve"
STUDENTS = [{"name": "Deon Menezes", "roll": "16014223030", "batch": "B1"},
            {"name": "Aishwarya Gawali", "roll": "16014223007", "batch": "B1"}]
AUTHORS = " & ".join(f"{s['name']} ({s['roll']})" for s in STUDENTS)
TITLE = "QuantSolve: a self-verifying, self-healing solver for quantitative problems"
COURSE = "Generative AI Laboratory, Lab CA"
THEME = ("Self-Correction 'Code Execution & Auto-Heal' Loop. Concept: ReAct (Reason + Act) / "
         "Reflexion Loops.")

# ------------------------------------------------------------------ styles

BODY = ParagraphStyle("body", fontName="Times-Roman", fontSize=11, leading=15,
                      alignment=TA_JUSTIFY, spaceAfter=6)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=14, bulletIndent=4, spaceAfter=3)
H1 = ParagraphStyle("h1", fontName="Times-Bold", fontSize=15, leading=19, textColor=NAVY,
                    spaceBefore=12, spaceAfter=7)
H2 = ParagraphStyle("h2", fontName="Times-Bold", fontSize=12.5, leading=16, textColor=NAVY,
                    spaceBefore=8, spaceAfter=4)
CAPTION = ParagraphStyle("caption", fontName="Times-Italic", fontSize=9.5, leading=12,
                         alignment=TA_CENTER, textColor=colors.HexColor("#444444"),
                         spaceBefore=3, spaceAfter=10)
CELL = ParagraphStyle("cell", fontName="Times-Roman", fontSize=9.5, leading=11.5)
CELL_B = ParagraphStyle("cellb", parent=CELL, fontName="Times-Bold", textColor=colors.white)
CODE = ParagraphStyle("code", fontName="Courier", fontSize=7.6, leading=9.4)


def clean(text: str) -> str:
    """Make arbitrary (LLM-written) text safe for a Paragraph in a Latin-1 Type 1 font."""
    table = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
             "—": " - ", "…": "...", "→": "->", "≤": "<=", "≥": ">=",
             "₹": "Rs ", " ": " ", "−": "-", "×": "x"}
    text = "".join(table.get(ch, ch) for ch in str(text))
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def bullets(items: list[str]) -> list[Paragraph]:
    return [Paragraph(item, BULLET, bulletText="•") for item in items]


def code_block(code: str, max_lines: int | None = None, width: int = 104) -> Table:
    lines = []
    for line in clean(code).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") \
            .rstrip("\n").splitlines():
        while len(line) > width:
            lines.append(line[:width])
            line = "    " + line[width:]
        lines.append(line)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines] + ["    ..."]
    block = Table([[Preformatted("\n".join(lines), CODE)]], colWidths=[TEXT_W])
    block.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
                               ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6),
                               ("TOPPADDING", (0, 0), (-1, -1), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return block


def table(rows: list[list], widths: list[float], header: bool = True,
          zebra: bool = True) -> Table:
    data = [[c if not isinstance(c, str) else Paragraph(c, CELL_B if (header and i == 0) else CELL)
             for c in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    if zebra:
        style += [("BACKGROUND", (0, i), (-1, i), LIGHT) for i in range(2, len(rows), 2)]
    t.setStyle(TableStyle(style))
    return t


def figure(path: Path, caption: str, width: float = TEXT_W,
           max_height: float = 660) -> KeepTogether:
    from PIL import Image as PILImage
    with PILImage.open(path) as im:
        w, h = im.size
    height = width * h / w
    if height > max_height:  # tall screenshots: shrink to fit one page with the caption
        width, height = max_height * w / h, max_height
    return KeepTogether([Image(str(path), width=width, height=height), p(caption, CAPTION)])


# ------------------------------------------------------------------ data

def load_json(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def all_traces() -> list[dict]:
    traces = []
    for path in sorted((ROOT / "runs").glob("*.json")) + sorted((ROOT / "runs" / "bench").glob("*.json")):
        trace = json.loads(path.read_text())
        trace["_path"] = path
        traces.append(trace)
    return traces


def is_correct(trace: dict) -> bool:
    task = tasks.TASKS.get(trace.get("task_id") or "")
    return bool(task and trace.get("result") and tasks.score(task, trace["result"])["correct"])


def pick_showcase(traces: list[dict], wanted: str | None) -> dict | None:
    """A logic-fault run that healed, is correct, and whose attempt-1 failure is attributable
    to the injected fault (the model's original program passes when re-run offline)."""
    if wanted:
        return next((t for t in traces if t["run_id"] == wanted), None)
    good = [t for t in traces if t.get("inject") == "logic" and t["success"]
            and len(t["attempts"]) >= 2 and is_correct(t)]
    good = [t for t in good if benchmark.injection_outcome(t) == "caught"]

    def rank(t: dict) -> tuple:  # saved CLI runs first, then a failed assert, then short runs
        return (t["_path"].parent.name == "runs", t["attempts"][0]["observation"]["kind"] == "assertion",
                -len(t["attempts"]), t["run_id"])

    return max(good, key=rank) if good else None


def pick_silent_case(traces: list[dict], wanted: str | None) -> dict | None:
    """A logic-fault run whose injected bug passed the checks on attempt 1 (wrong answer)."""
    if wanted:
        return next((t for t in traces if t["run_id"] == wanted), None)
    silent = [t for t in traces if t.get("inject") == "logic" and t["success"] and not is_correct(t)
              and len(t["attempts"]) == 1 and benchmark.injection_outcome(t) == "silent"]

    def wrong_keys(t: dict) -> int:
        checks = tasks.score(tasks.TASKS[t["task_id"]], t["result"])["checks"]
        return sum(not c["ok"] for c in checks.values())

    return max(silent, key=lambda t: (t["_path"].parent.name == "runs", wrong_keys(t), t["run_id"]),
               default=None)


def pick_unhealed_case(traces: list[dict], wanted: str | None) -> dict | None:
    """An injected run that used every attempt without passing its own checks."""
    if wanted:
        return next((t for t in traces if t["run_id"] == wanted), None)
    failed = [t for t in traces if t.get("inject") and not t["success"] and len(t["attempts"]) >= 3]
    return max(failed, key=lambda t: (t["_path"].parent.name == "runs", t["run_id"]), default=None)


_TABLES = {"n": 0}


def next_table() -> int:
    _TABLES["n"] += 1
    return _TABLES["n"]


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


# ------------------------------------------------------------------ sections

def cover(story: list, model: str) -> None:
    story += [Spacer(1, 3.2 * cm),
              p(f"<font size=22 color='#1f3a5f'><b>QuantSolve</b></font>",
                ParagraphStyle("t", fontName="Times-Bold", alignment=TA_CENTER, leading=28)),
              Spacer(1, 0.3 * cm),
              p("A self-verifying, self-healing solver for quantitative problems",
                ParagraphStyle("st", fontName="Times-Italic", fontSize=15, leading=19,
                               alignment=TA_CENTER, textColor=NAVY)),
              Spacer(1, 1.2 * cm),
              p(f"<b>{COURSE}</b>", ParagraphStyle("c", fontName="Times-Roman", fontSize=13,
                                                    alignment=TA_CENTER, leading=17)),
              Spacer(1, 0.4 * cm),
              p(clean(THEME) + "<br/>Task: build a Python execution loop that generates code for a "
                "complex task, runs it in a safe execution environment, captures tracebacks on "
                "failure and iteratively fixes the code.",
                ParagraphStyle("th", fontName="Times-Roman", fontSize=11, leading=15,
                               alignment=TA_CENTER, leftIndent=1.5 * cm, rightIndent=1.5 * cm)),
              Spacer(1, 1.6 * cm)]
    info = Table([["Name", "Roll No", "Batch"]]
                 + [[s["name"], s["roll"], s["batch"]] for s in STUDENTS],
                 colWidths=[6 * cm, 4 * cm, 2.5 * cm])
    info.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Times-Roman", 12),
                              ("FONT", (0, 0), (-1, 0), "Times-Bold", 12),
                              ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                              ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                              ("GRID", (0, 0), (-1, -1), 0.6, RULE),
                              ("TOPPADDING", (0, 0), (-1, -1), 7),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                              ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    story += [info, Spacer(1, 0.45 * cm),
              p(f"GitHub repository: <link href='{REPO}' color='#1f4e9c'><u>{REPO}</u></link>",
                ParagraphStyle("gh", fontName="Times-Roman", fontSize=12, alignment=TA_CENTER)),
              Spacer(1, 0.3 * cm),
              p(f"Date: {date.today().strftime('%d %B %Y')}",
                ParagraphStyle("d", fontName="Times-Roman", fontSize=12, alignment=TA_CENTER)),
              Spacer(1, 1.7 * cm),
              p("Execution engine: restricted <font face='Courier'>exec()</font> inside a "
                f"child process &nbsp;|&nbsp; Model: {clean(model)} (OpenAI API)",
                ParagraphStyle("f", fontName="Times-Roman", fontSize=10.5, alignment=TA_CENTER,
                               textColor=colors.HexColor("#555555"))),
              PageBreak()]


def aim_objectives(story: list) -> None:
    story += [p("1. Aim", H1),
              p("To design, build and evaluate a Python execution loop that takes a quantitative "
                "word problem, asks a large language model to write a program for it, runs the "
                "program in a restricted <font face='Courier'>exec()</font> sandbox, captures the "
                "traceback or failed self-check when something goes wrong, and repairs the "
                "program over several attempts using the ReAct and Reflexion ideas."),
              p("2. Objectives", H1)]
    story += bullets([
        "Generate complete Python programs from natural-language problems under a strict "
        "contract: the program computes everything, stores its answer in a <font "
        "face='Courier'>RESULT</font> dictionary and contains at least two <font "
        "face='Courier'>assert</font> self-checks.",
        "Execute untrusted generated code with layered defences: an AST safety gate, restricted "
        "builtins with a guarded import, a separate child process with a scrubbed environment, "
        "a CPU limit, a memory watchdog and a wall-clock timeout.",
        "Classify every failure (blocked, syntax, runtime, assertion, timeout, contract) and "
        "return a cleaned traceback to the model as the Observation.",
        "Add Reflexion-style verbal self-reflection stored in an episodic memory, plus a loop "
        "guard that notices repeated code or repeated errors.",
        "Provide a command-line interface and a web application (FastAPI backend and a "
        "hand-built single-page front end) that stream each Thought, Action, Observation and "
        "Reflection live, and save a full JSON trace of every run.",
        "Measure the effect of the loop against one-shot generation on eight problems with "
        "hand-written reference answers, including runs where a bug is deliberately injected, "
        "and test the sandbox against known escape and resource-exhaustion attacks."])


def theory(story: list) -> None:
    story += [p("3. Theory", H1),
              p("3.1 LLM code generation and why a feedback loop is needed", H2),
              p("Large language models write code that usually looks right. For numerical "
                "problems the typical failure is not a wild hallucination but a small slip: a "
                "misspelled variable, a loop that runs one step too few, a sign error, a value "
                "that is rounded too early, or a library call with the wrong arguments. In "
                "one-shot generation nothing notices these slips; the program either crashes or, "
                "worse, prints a plausible but wrong number. Executing the code gives the system "
                "an external, objective signal (the interpreter does not care how confident the "
                "model sounded), and feeding that signal back lets the model correct itself."),
              p("3.2 Program-aided reasoning (PAL, Program of Thoughts)", H2),
              p("PAL (Gao et al., 2023) and Program of Thoughts (Chen et al., 2022) separate "
                "reasoning from calculation: the model writes the reasoning as a program and the "
                "Python interpreter performs the arithmetic. This removes the arithmetic errors "
                "that language models make when they compute in text, and it makes the reasoning "
                "inspectable. QuantSolve follows this pattern: the model never states the final "
                "number itself; it only writes the program that computes it."),
              p("3.3 ReAct: reasoning and acting", H2),
              p("ReAct (Yao et al., 2023) interleaves free-text reasoning traces with actions in "
                "an environment, and uses the observation returned by each action to decide the "
                "next step. In QuantSolve one attempt is one ReAct step: the <i>Thought</i> is the "
                "model's short plan (method, formulas, which invariants it will check), the "
                "<i>Action</i> is the program, and the <i>Observation</i> is the sandbox result "
                "(a RESULT dictionary, or a failure kind with a cleaned traceback)."),
              p("3.4 Reflexion and Self-Refine", H2),
              p("Reflexion (Shinn et al., 2023) improves an agent across trials without changing "
                "any weights. After a failed trial the model writes a short verbal reflection on "
                "what went wrong; the reflection is kept in an episodic memory and added to the "
                "prompt of later trials. Self-Refine (Madaan et al., 2023) is a related loop in "
                "which the same model gives feedback on its own output and then refines it. "
                "QuantSolve uses a separate reflection call after every failure that returns a "
                "diagnosis, a lesson and a next plan; all reflections so far are shown to every "
                "later attempt."),
              p("3.5 Self-verification with assertions", H2),
              p("The interpreter only reports crashes. A program that runs to completion with a "
                "logic error produces a wrong answer with no traceback at all. To turn silent "
                "errors into observable ones, the code contract requires at least two assertions "
                "that compare quantities computed in different ways, for example a month-by-month "
                "loan simulation against the closed-form total interest, or a dynamic-programming "
                "count against a brute-force count. A failed assertion becomes an Observation "
                "like any other error. The weakness is that the same model writes the checks: a "
                "check can itself be wrong (a false alarm) or too weak to notice a real error "
                "(a silent pass). Both effects show up in the results."),
              p("3.6 Sandboxing with exec()", H2),
              p("Python's <font face='Courier'>exec()</font> with a custom globals dictionary is "
                "convenient but it is not a security boundary: through object introspection (for "
                "example <font face='Courier'>().__class__.__base__.__subclasses__()</font>), "
                "generator frames or modules that re-export <font face='Courier'>os</font> and "
                "<font face='Courier'>sys</font>, code can reach the rest of the interpreter. The "
                "practical answer is defence in depth: reject dangerous constructs before running "
                "(static AST analysis), give the code only a curated set of builtins, run it in a "
                "separate process that holds no secrets, and bound its CPU time, memory and wall "
                "time so that it cannot hang or exhaust the host.")]


def architecture(story: list) -> None:
    story += [p("4. System architecture", H1),
              p("Figure 1 shows the loop. A task goes to the solver prompt, which returns a "
                "thought and a program in JSON mode. In demo or benchmark runs the fault injector "
                "can corrupt the first program. The program then passes through the AST safety "
                "gate, runs in a fresh child process and is checked against the contract. If it "
                "passes, its RESULT is summarised in plain English. If any stage fails, the "
                "failure becomes the Observation, a reflection is written and stored in memory, "
                "and the next attempt receives the previous code, the observation, the whole "
                "memory and, if the loop guard fired, a nudge to change approach."),
              figure(FIG / "fig_loop.png", "Figure 1. The QuantSolve loop: ReAct steps (Thought, "
                     "Action, Observation) with Reflexion memory between attempts.",
                     width=TEXT_W * 0.9)]


def implementation(story: list) -> None:
    modules = [("config.py", "Settings dataclass loaded from .env (model, max attempts, timeout, "
                "temperatures)."),
               ("llm.py", "OpenAI chat wrapper in JSON mode with a simple retry and token/cost "
                "accounting (" + "; ".join(f"{m}: ${a:.2f} / ${b:.2f}" for m, (a, b)
                                           in llm.PRICES_PER_M.items())
                + " per million input / output tokens)."),
               ("prompts.py", "Solve, reflect and summarise prompts, and the formatting of "
                "observations and memory."),
               ("sandbox.py", "AST safety gate, restricted builtins, child-process runner, failure "
                "classification and traceback cleaning."),
               ("faults.py", "Deterministic AST-based bug injection (crash and logic modes)."),
               ("agent.py", "The ReAct + Reflexion loop, loop guard, events for the UI, and JSON "
                "traces."),
               ("tasks.py", "Eight problems with hand-written reference solutions and scoring."),
               ("benchmark.py, safety_eval.py", "The two evaluation scripts."),
               ("cli.py, web.py", "Rich command-line interface; launcher for the website."),
               ("webapp/*.py", "FastAPI server: JSON API, Server-Sent Events stream of loop "
                "events, background solve jobs with a stop flag, read-only data loaders."),
               ("webapp/static/", "Hand-written HTML, CSS and JavaScript front end (no framework, "
                "no build step): live run view, history, results, explainer.")]
    rows = [["Module", "Lines", "Responsibility"]]
    for name, desc in modules:
        if name == "webapp/*.py":
            files = sorted((ROOT / "webapp").glob("*.py"))
        elif name == "webapp/static/":
            files = [f for f in sorted((ROOT / "webapp" / "static").rglob("*"))
                     if f.suffix in (".html", ".css", ".js")]
        else:
            files = [ROOT / "quantsolve" / n.strip() if not n.strip().endswith(("cli.py", "web.py"))
                     else ROOT / n.strip() for n in name.split(",")]
        lines = sum(len(f.read_text().splitlines()) for f in files if f.exists())
        rows.append([f"<font face='Courier'>{name}</font>", str(lines), desc])
    story += [p("5. Implementation", H1),
              p("The project is written in Python 3.13 with module-level functions and "
                "dataclasses rather than class hierarchies, so that the core package can be read "
                "in one sitting. Table 1 lists the modules."),
              table(rows, [3.6 * cm, 1.3 * cm, TEXT_W - 4.9 * cm]),
              p("Table 1. Modules of the <font face='Courier'>quantsolve</font> package and the "
                "two front ends (line counts measured when this report was built).", CAPTION),
              p("5.1 Sandbox design", H2),
              p("Execution happens in three stages. <b>(1) Static checks in the parent.</b> The "
                "code is parsed; a syntax error is reported with its line. The AST gate then "
                "rejects imports outside the allow-list (" + ", ".join(sorted(ALLOWED_MODULES)) +
                "), relative and star imports, the names <font face='Courier'>eval, exec, "
                "compile, open, __import__, input, breakpoint, exit, quit, globals, locals, vars, "
                "getattr, setattr, delattr, memoryview</font>, any attribute starting with an "
                "underscore (this covers every dunder as well as private module attributes such as "
                "<font face='Courier'>random._os</font>), a list of attributes that lead out of "
                "the sandbox without a dunder (frame and generator internals such as <font "
                "face='Courier'>gi_frame</font> and <font face='Courier'>f_back</font>, modules "
                "re-exported by allowed modules such as <font face='Courier'>statistics.sys</font>, "
                "and numpy file I/O such as <font face='Courier'>load</font> and <font "
                "face='Courier'>tofile</font>), and format strings that read such attributes. "
                "A test walks every public attribute reachable from the allowed modules and "
                "confirms that no dangerous module can be reached. Programs with fewer than two "
                "assert statements are rejected as a contract violation before they run."),
              p("<b>(2) A fresh child process.</b> The parent starts a "
                "<font face='Courier'>multiprocessing</font> child with the \"spawn\" start method; "
                "the target function lives in <font face='Courier'>sandbox.py</font> so it can be "
                "pickled from the CLI, from the web server's worker threads, or from standard "
                "input. The child first "
                "deletes every environment variable except a few harmless ones (so the OpenAI key "
                "is not present), sets <font face='Courier'>RLIMIT_CPU</font>, starts a watchdog "
                "thread that kills the process if its resident memory exceeds 1 GB (macOS ignores "
                "memory rlimits), redirects stdout and stderr, and calls <font face='Courier'>"
                "exec(compile(code, \"&lt;solution&gt;\", \"exec\"), ns)</font> where <font "
                "face='Courier'>ns</font> holds only <font face='Courier'>SAFE_BUILTINS</font>. "
                "That dictionary contains common functions and exception classes, <font "
                "face='Courier'>__build_class__</font> so that classes work, and a guarded "
                "<font face='Courier'>__import__</font> that re-checks the allow-list at run time "
                "(it has to allow private sub-modules of allowed packages, because C code such as "
                "<font face='Courier'>ndarray.mean</font> imports them lazily through the calling "
                "frame's builtins). <b>(3) Classification.</b> The child sends back a small "
                "dictionary over a pipe: success flag, RESULT (checked to be a JSON-serialisable "
                "dict), truncated stdout, exception type and message, and a traceback restricted "
                "to frames in <font face='Courier'>&lt;solution&gt;</font> with each source line "
                "pulled from the code string. The parent waits for a \"ready\" message and then "
                "applies the timeout to the user code only; if it expires the child is terminated "
                "and then killed.")]
    kinds = [["Kind", "Raised when", "Example observation"],
             ["blocked", "The AST gate finds a forbidden import, name, attribute or string.",
              "line 1: import of 'os' is not allowed"],
             ["syntax", "The code does not parse.", "SyntaxError: '(' was never closed (line 1)"],
             ["runtime", "Any exception other than AssertionError; also the memory watchdog.",
              "NameError: name 'annual_raet' is not defined. Did you mean: 'annual_rate'?"],
             ["assertion", "A self-check failed: the program is internally inconsistent.",
              "AssertionError: interest mismatch: 5413573.61 vs 5413878.80"],
             ["timeout", "Wall-clock limit (default 10 s) or the CPU rlimit was hit.",
              "Execution exceeded the 10 s time limit and the process was killed"],
             ["contract", "Fewer than 2 asserts, RESULT missing, not a dict, or not JSON.",
              "RESULT is not JSON-serialisable (Object of type set is not JSON serializable)"]]
    story += [p("5.2 Failure taxonomy", H2),
              table([[clean(c) if i else c for c in row] for i, row in enumerate(kinds)],
                    [2.0 * cm, 6.2 * cm, TEXT_W - 8.2 * cm]),
              p("Table 2. Failure kinds returned to the model as the Observation.", CAPTION)]

    story += [p("5.3 Prompts", H2),
              p("All prompts live in <font face='Courier'>prompts.py</font> and use JSON mode. "
                "The <b>solve</b> prompt states the code contract: allowed imports only; no file, "
                "network or introspection features; compute every number in code; assign the "
                "requested keys to <font face='Courier'>RESULT</font> with plain JSON values; and "
                "write at least two assertions that compare quantities obtained in different ways, "
                "with tolerances for floats and the values in the message. The model returns "
                "<font face='Courier'>{\"thought\", \"code\"}</font>. On later attempts the prompt "
                "also carries the previous program, the observation and the numbered Reflexion "
                "memory, and asks for a complete corrected program that fixes the root cause "
                "without weakening the checks. The <b>reflect</b> prompt asks for <font "
                "face='Courier'>{\"diagnosis\", \"reflection\", \"next_plan\"}</font> in at most "
                "two sentences each, citing the failing line, and reminds the model that a failed "
                "assertion means two quantities disagree, so it must decide which side is wrong "
                "rather than delete the check. The <b>summarise</b> prompt turns the verified "
                "RESULT into a short plain-English answer without recomputing anything."),
              p("5.4 Loop guard and fault injection", H2),
              p("After each failure the agent hashes the normalised AST of the code (so comment "
                "or whitespace changes do not count as new code) and forms an error signature "
                "(kind, exception type, line). If either has been seen before, the next prompt "
                "carries a nudge to change approach and the solver temperature is raised for that "
                "call; for repeated assertion failures the nudge suggests checking both sides of "
                "the assertion on a tiny case. The fault injector, used only on attempt 1, "
                "rewrites the program with <font face='Courier'>ast.NodeTransformer</font>: "
                "<i>crash</i> renames one use of a variable to a misspelling (NameError), and "
                "<i>logic</i> makes the first <font face='Courier'>for ... in range()</font> loop "
                "stop one step early, or flips the first + or - inside a loop. Logic faults rarely "
                "crash (an index error or an endless loop is possible), so usually only the "
                "program's own assertions can notice them."),
              p("5.5 Key code: the loop", H2),
              p("The excerpt below is read from <font face='Courier'>quantsolve/agent.py</font> "
                "when this report is built (event emission and bookkeeping lines included)."),
              code_block(loop_excerpt())]


def loop_excerpt() -> str:
    source = (ROOT / "quantsolve" / "agent.py").read_text().splitlines()
    start = next(i for i, l in enumerate(source) if l.strip().startswith("for number in range"))
    end = next(i for i, l in enumerate(source) if l.strip().startswith("trace.success = obs.ok"))
    lines = [l[4:] for l in source[start:end]]
    return "\n".join(l for l in lines if l.strip())


def walkthrough(story: list, trace: dict | None) -> None:
    story += [p("6. Walkthrough of real runs", H1), p("6.1 An injected bug that was caught and healed", H2)]
    if not trace:
        story.append(p("No saved run with an injected logic bug that healed was found."))
        return
    attempts = trace["attempts"]
    first, last = attempts[0], attempts[-1]
    obs1 = first["observation"]
    task = tasks.TASKS.get(trace.get("task_id") or "")
    graded = tasks.score(task, trace["result"]) if task else None
    story += [p(f"This section follows run <font face='Courier'>{clean(trace['run_id'])}</font> "
                f"(model {clean(trace['model'])}), taken from the saved JSON trace. The task was "
                f"<i>{clean(task.title if task else trace['task'][:80])}</i>; the full problem "
                "text is in <font face='Courier'>quantsolve/tasks.py</font>. A <b>logic</b> fault "
                f"was injected into attempt 1, and the run finished after {len(attempts)} attempts "
                f"using {trace['usage']['calls']} LLM calls, {trace['usage']['total_tokens']:,} "
                f"tokens and about ${trace['usage']['cost_usd']:.4f}."),
              p("Because the fault is injected after the model has written the program, it is "
                "fair to ask whether attempt 1 failed because of the fault or because of a bug "
                "the model wrote itself. Re-running the model's original attempt-1 program "
                "offline gives the answer: "
                + {"caught": "it passes every self-check, so the failure below is caused by "
                             "the injected fault.",
                   "original_failed": "it fails too, so the failure cannot be credited to the "
                                      "injected fault."}.get(benchmark.injection_outcome(trace),
                                                             "see the trace.")),
              p("<b>Attempt 1, Thought.</b> " + clean(first["thought"])),
              p("<b>Injected fault.</b> " + clean(first["injected"] or "none")),
              p("The executed program around the corrupted line was:")]
    line_no = int(m.group(1)) if (m := re.search(r"line (\d+)", first["injected"] or "")) else 1
    code_lines = first["code"].splitlines()
    lo, hi = max(line_no - 4, 0), min(line_no + 6, len(code_lines))
    story += [code_block("\n".join(f"{i + 1:3d}  {code_lines[i]}" for i in range(lo, hi))),
              p(f"<b>Observation 1</b> (kind <i>{obs1['kind']}</i>):"),
              code_block(obs1.get("traceback") or obs1["message"], max_lines=14)]
    if first.get("reflection"):
        r = first["reflection"]
        story += [p("<b>Reflection 1</b> (stored in memory). <i>Diagnosis:</i> "
                    f"{clean(r['diagnosis'])} <i>Lesson:</i> {clean(r['reflection'])} "
                    f"<i>Next plan:</i> {clean(r['next_plan'])}")]
    for a in attempts[1:-1]:
        o = a["observation"]
        story.append(p(f"<b>Attempt {a['number']}</b> failed again with kind <i>{o['kind']}</i>: "
                       f"{clean(o['message'].splitlines()[0][:220])}"
                       + (f" Reflection: {clean(a['reflection']['reflection'])}"
                          if a.get("reflection") else "")))
    story += [p(f"<b>Attempt {last['number']}, Thought.</b> " + clean(last["thought"])),
              p("The change between the failing program and the final program (unified diff, "
                "comments and blank lines ignored):")]
    diff = list(difflib.unified_diff(_code_lines(first["code"]), _code_lines(last["code"]),
                                     "attempt 1 (executed)", f"attempt {last['number']}",
                                     lineterm="", n=1))
    story += [code_block("\n".join(diff) if diff else "(no textual change)", max_lines=34),
              p(f"<b>Observation {last['number']}</b>: all {last['observation']['asserts']} "
                "self-checks passed and the program returned "
                f"<font face='Courier'>{clean(json.dumps(trace['result']))}</font>.")]
    if graded:
        story.append(p("Scored against the hand-written reference, the result is "
                       f"<b>{'correct' if graded['correct'] else 'wrong'}</b> ("
                       + "; ".join(f"{clean(k)}: expected {c['expected']}, got {c['got']}"
                                   for k, c in graded["checks"].items()) + ")."))
    story.append(p("<b>Final answer.</b> " + clean(trace["final_answer"])))


def failure_cases(story: list, silent: dict | None, unhealed: dict | None) -> None:
    section = 2
    for trace, render in ((silent, _silent_case), (unhealed, _unhealed_case)):
        if trace:
            render(story, trace, tasks.TASKS.get(trace.get("task_id") or ""), f"6.{section}")
            section += 1


def _silent_case(story: list, trace: dict, task, number: str) -> None:
    first = trace["attempts"][0]
    original = sandbox.run(first["llm_code"])
    ref = tasks.reference_answer(task.id) if task else {}
    graded = tasks.score(task, trace["result"]) if task else {"checks": {}}
    orig_graded = tasks.score(task, original.result) if task and original.ok else None
    n = next_table()
    rows = [["RESULT key", "Reference", "Returned (with the bug)", "Model's original program"]]
    for key, c in graded["checks"].items():
        orig = (original.result or {}).get(key, "-")
        rows.append([f"<font face='Courier'>{clean(key)}</font>", str(c["expected"]),
                     str(c["got"]) + ("" if c["ok"] else " (wrong)"), str(orig)])
    asserts = [line.strip() for line in first["code"].splitlines()
               if line.strip().startswith("assert ")]
    story += [p(f"{number} An injected bug that slipped past the self-checks", H2),
              p(f"Run <font face='Courier'>{clean(trace['run_id'])}</font> "
                f"({clean(task.title if task else 'free text')}) shows the most important failure "
                f"mode. The injector made this change: {clean(first['injected'])}. The mutated "
                f"program still passed all {first['observation']['asserts']} of its "
                "self-checks on attempt 1, so the loop had nothing to react to: it stopped and "
                f"returned a wrong answer. Table {n} compares the returned RESULT with the "
                "reference and with the model's original (un-mutated) program, re-run offline.")]
    story += [table(rows, [3.6 * cm, 3.2 * cm, 4.2 * cm, TEXT_W - 11.0 * cm]),
              p(f"Table {n}. A silent failure: the injected bug changed the answer but not the "
                "outcome of the checks.", CAPTION),
              p("The self-checks in that program were:"),
              code_block("\n".join(asserts) or "(none found)")]
    if orig_graded:
        ok_keys = sum(c["ok"] for c in orig_graded["checks"].values())
        story.append(p(f"The model's original program gets {ok_keys} of "
                       f"{len(orig_graded['checks'])} keys right, so its method was sound and the "
                       "injected bug alone made the answer wrong. The checks it wrote were true "
                       "of both the correct and the corrupted program, which is exactly the "
                       "weakness of self-written assertions: they only protect the quantities "
                       "they actually compare."))


def _unhealed_case(story: list, trace: dict, task, number: str) -> None:
    attempts = trace["attempts"]
    first = attempts[0]
    outcome = benchmark.injection_outcome(trace)
    n = next_table()
    rows = [["#", "Observation", "Reflection: diagnosis (shortened)", "Loop guard"]]
    for a in attempts:
        o = a["observation"]
        diag = (a.get("reflection") or {}).get("diagnosis", "")
        rows.append([str(a["number"]),
                     f"<i>{o['kind']}</i>: {clean((o['message'].splitlines() or [''])[0][:110])}",
                     clean(diag[:170] + ("..." if len(diag) > 170 else "")) or "-",
                     clean(a["nudge"].split(".")[0]) if a.get("nudge") else "-"])
    story += [p(f"{number} A run that did not heal", H2),
              p(f"Run <font face='Courier'>{clean(trace['run_id'])}</font> "
                f"({clean(task.title if task else 'free text')}, {trace['inject']} fault) shows the "
                f"limits of the loop. It used all {len(attempts)} attempts without passing. The "
                f"injected fault was: {clean(first['injected'] or 'none')}. Table {n} lists what "
                "each attempt observed.")]
    story += [table(rows, [0.7 * cm, 5.2 * cm, TEXT_W - 9.4 * cm, 3.5 * cm]),
              p(f"Table {n}. Observations of the run that did not heal.", CAPTION)]
    ref = tasks.reference_answer(task.id) if task else {}
    late = [a["observation"]["message"] for a in attempts[1:]]
    numbers = [float(x) for x in re.findall(r"-?\d+\.\d+", late[-1])] if late else []
    matches_ref = [k for k, v in ref.items() if numbers and isinstance(v, (int, float))
                   and abs(numbers[0] - v) <= max(1.0, 1e-6 * abs(v))]
    text = []
    line = re.search(r"line (\d+)", first.get("injected") or "")
    diag1 = (first.get("reflection") or {}).get("diagnosis", "")
    if line and f"line {line.group(1)}" in diag1 and outcome != "not_applied":
        text.append(f"The first reflection pointed at line {line.group(1)}, where the fault had "
                    "been injected.")
    if attempts[1]["observation"]["message"] != first["observation"]["message"]:
        text.append("Attempt 2 no longer failed on the first check, but a different check then "
                    "failed and kept failing.")
    if outcome == "original_failed":
        text.append("Re-running the model's original attempt-1 program offline shows that it "
                    "also failed, so the check that kept failing was the model's own problem, "
                    "present before the fault was injected.")
    if matches_ref:
        text.append(f"The left-hand value in the failing assertion equals the reference "
                    f"<font face='Courier'>{clean(matches_ref[0])}</font> ({ref[matches_ref[0]]}), "
                    "so the main computation was right and the model's independent check was the "
                    "wrong side: a false alarm. Any reflection that blamed the computation (see "
                    "the diagnosis column) sent the next attempt in the wrong direction.")
    if sum(bool(a.get("nudge")) for a in attempts) >= 2:
        text.append("The loop guard fired, but the model kept repeating the same approach.")
    story.append(p(" ".join(text) or "See the saved trace for details."))


def _code_lines(code: str) -> list[str]:
    out = []
    for line in code.splitlines():
        stripped = line.split("#")[0].rstrip() if "#" in line and "'" not in line and '"' not in line \
            else line.rstrip()
        if stripped.strip():
            out.append(stripped)
    return out


def results(story: list, bench: dict | None) -> None:
    story += [p("7. Results", H1)]
    if not bench:
        story.append(p("results/benchmark.json was not found; run <font face='Courier'>python3 "
                       "cli.py bench</font> first."))
        return
    meta, summary, rows = bench["meta"], bench["summary"], bench["runs"]
    t_tasks, t_summary = next_table(), next_table()
    task_rows = [["Id", "Problem", "Scored RESULT keys"]] + [
        [f"<font face='Courier'>{t.id}</font>", clean(t.title), clean(", ".join(t.keys))]
        for t in tasks.TASKS.values() if t.id in meta["tasks"]]
    story += [p("7.1 Setup", H2),
              p(f"The benchmark uses the {len(meta['tasks'])} problems in Table {t_tasks}. Each is a "
                "multi-step problem whose text states every rule and the exact RESULT keys and "
                "units, and each has a hand-written reference solution that is cross-checked by "
                "an independent method in the test suite (for example a year-by-year closed form "
                "for the loan, a generating function for the birthday triples, an RK4 simulation "
                "for the projectile). A run is <i>correct</i> only if every scored key is within "
                "its tolerance. Every case was run "
                f"{meta.get('repeats', 1)} time(s) with model {clean(meta['model'])}, at most "
                f"{meta['max_attempts']} attempts and a {meta['timeout_s']:g} s sandbox timeout. "
                "The arms are: <b>one-shot</b> (one attempt, no healing), <b>loop</b> (the full "
                "QuantSolve loop), <b>loop + logic bug</b> (a logic fault injected into attempt 1) "
                "and <b>loop + crash bug</b> (a crash fault on attempt 1, run on "
                f"{len(meta['crash_tasks'])} tasks)."),
              table(task_rows, [3.6 * cm, 6.4 * cm, TEXT_W - 10 * cm]),
              p(f"Table {t_tasks}. Benchmark problems.", CAPTION)]

    arms = [a for a in figures.ARM_COLORS if a in summary]
    srow = [["Arm", "Runs", "Correct", "Verified", "Verified but wrong", "Avg attempts",
             "Healed", "Tokens", "Cost (USD)"]]
    for a in arms:
        s = summary[a]
        srow.append([figures.ARM_LABELS[a], str(s["runs"]), f"{s['correct']} ({pct(s['accuracy'])})",
                     str(s["verified"]), str(s["verified_but_wrong"]), f"{s['avg_attempts']:.2f}",
                     str(s["healed"]), f"{s['tokens']:,}", f"{s['cost_usd']:.4f}"])
    total_cost = sum(summary[a]["cost_usd"] for a in arms)
    total_runs = sum(summary[a]["runs"] for a in arms)
    story += [p("7.2 Overall comparison", H2),
              table(srow, [2.9 * cm, 1.1 * cm, 1.9 * cm, 1.5 * cm, 1.9 * cm, 1.7 * cm, 1.4 * cm,
                           1.6 * cm, TEXT_W - 14.0 * cm]),
              p(f"Table {t_summary}. Benchmark summary ({clean(meta['model'])}). <i>Verified</i>: the final program passed its own "
                "self-checks. <i>Verified but wrong</i>: it passed them but disagreed with the "
                "reference. <i>Healed</i>: attempt 1 failed and a later attempt passed.", CAPTION),
              figure(figures.arm_bars(summary, FIG / "fig_arms.png"),
                     "Figure 2. Accuracy, average attempts and average cost per run for each arm.")]
    one, loop = summary.get("one_shot"), summary.get("quantsolve")
    text = []
    if one and loop:
        diff = 100 * (loop["accuracy"] - one["accuracy"])
        verb = "raised" if diff > 0 else "lowered" if diff < 0 else "did not change"
        amount = f" by {abs(diff):.0f} percentage points" if diff else ""
        text.append(f"Across {one['runs']} runs per arm, the loop {verb} accuracy{amount}, from "
                    f"{pct(one['accuracy'])} for one-shot generation to {pct(loop['accuracy'])}. "
                    f"It needed {loop['avg_attempts']:.2f} attempts per run on average and healed "
                    f"{loop['healed']} run(s) whose first program failed. The price is cost: a loop "
                    f"run cost {loop['cost_usd'] / max(loop['runs'], 1) * 100:.2f} US cents on "
                    f"average against {one['cost_usd'] / max(one['runs'], 1) * 100:.2f} cents for "
                    "one-shot.")
        kinds = one["failure_kinds"]
        common = (f" (most often <i>{max(kinds, key=kinds.get)}</i>)" if kinds else "")
        text.append(f"In the one-shot arm {one['runs'] - one['verified']} of {one['runs']} first "
                    f"programs failed in the sandbox{common}, which is the room the loop has to "
                    "work with. On the other hand "
                    f"{loop['verified_but_wrong']} loop run(s) ended with a program that passed its "
                    "own checks but was still wrong: the assertions only test what the model "
                    "thought to test.")
    inj = summary.get("quantsolve+inject")
    if inj:
        text.append(f"With a logic bug injected into attempt 1, the first program failed in "
                    f"{inj['inject_detected']} of {inj['runs']} runs (the injector found a place "
                    f"to mutate in {inj['inject_applied']}). Not every such failure was caused by "
                    "the fault, because the model's own program often had problems too; Section "
                    "7.4 separates the two. This arm reached "
                    f"{pct(inj['accuracy'])} accuracy with {inj['avg_attempts']:.2f} attempts on "
                    "average.")
    crash = summary.get("quantsolve+crash")
    if crash:
        text.append(f"In the crash arm {crash['healed']} of {crash['runs']} runs recovered from a "
                    "failed first attempt and the arm reached "
                    f"{pct(crash['accuracy'])} accuracy; for a NameError the cleaned traceback "
                    "names the line and even suggests the correct variable, so the repair itself "
                    "is easy.")
    text.append(f"The whole benchmark ({total_runs} runs) cost ${total_cost:.4f}.")
    story += [p(" ".join(text[:2])), p(" ".join(text[2:]))]
    model_comparison(story, bench)

    inj_rows = [["Arm", "Caught", "Silent", "Benign", "Original failed", "Not applied"]]
    labels = ["caught", "silent", "benign", "original_failed", "not_applied"]
    for a in ("quantsolve+inject", "quantsolve+crash"):
        if a in summary:
            outcomes = summary[a].get("inject_outcomes", {})
            inj_rows.append([figures.ARM_LABELS[a]] + [str(outcomes.get(k, 0)) for k in labels])
    if len(inj_rows) > 1:
        logic = summary.get("quantsolve+inject", {}).get("inject_outcomes", {})
        attributable = sum(logic.get(k, 0) for k in ("caught", "silent", "benign"))
        t_inj = next_table()
        story += [p("7.4 Did the self-checks catch the injected bugs?", H2),
                  p("A failed first attempt in an injected run does not prove that the checks "
                    "caught the fault: the model may have written its own bug as well. For every "
                    "injected run the model's original attempt-1 program was therefore re-run "
                    "offline. <i>Caught</i>: the original passes but the mutated program fails. "
                    "<i>Silent</i>: both pass but the numbers differ, so wrong numbers got through "
                    "the checks. <i>Benign</i>: both pass with identical numbers (the mutated loop "
                    "did not matter). <i>Original failed</i>: the model's own program already "
                    "failed, so nothing can be attributed to the fault. <i>Not applied</i>: the "
                    "injector found no place to mutate (for example, the code did not parse)."),
                  table(inj_rows, [3.6 * cm] + [(TEXT_W - 3.6 * cm) / 5] * 5),
                  p(f"Table {t_inj}. Attribution of attempt-1 outcomes in the injected-bug arms.",
                    CAPTION)]
        if attributable:
            caught, silent = logic.get("caught", 0), logic.get("silent", 0)
            verdict = ("most of the logic bugs that changed the answer slipped through and became "
                       "verified-but-wrong answers" if silent > caught else
                       "the checks caught most, but not all, of the logic bugs that changed the "
                       "answer" if silent else "every logic bug that changed the answer was caught")
            story.append(p(f"Of the {attributable} logic faults that could be attributed, the "
                           f"checks caught {caught}, {silent} slipped through silently and "
                           f"{logic.get('benign', 0)} changed nothing. This is the most direct "
                           "measurement of self-verification in the project: here "
                           f"{verdict}. Crash faults, by contrast, are caught whenever the fault is "
                           "the first thing to go wrong, because the interpreter itself raises the "
                           "error."))

    story += [p("7.5 Failure kinds and per-task behaviour", H2),
              figure(figures.failure_kinds(summary, FIG / "fig_failure_kinds.png"),
                     "Figure 3. Failed attempts by failure kind for each arm.", width=TEXT_W * 0.8)]
    kinds_total: dict[str, int] = {}
    for a in arms:
        for k, v in summary[a]["failure_kinds"].items():
            kinds_total[k] = kinds_total.get(k, 0) + v
    if kinds_total:
        top_kind = max(kinds_total, key=kinds_total.get)
        story.append(p(f"Over all arms, {sum(kinds_total.values())} attempts failed; the most "
                       f"common kind was <i>{top_kind}</i> ({kinds_total[top_kind]} attempts). "
                       + ", ".join(f"{k}: {v}" for k, v in sorted(kinds_total.items(),
                                                                   key=lambda kv: -kv[1]))
                       + ". "
                       + ("Assertion failures dominating is the intended effect of the contract: "
                          "problems that would otherwise have produced a quietly wrong number are "
                          "surfaced as an Observation the model can act on. " if top_kind == "assertion" else "")
                       + "The other side is that an assertion failure can be a false alarm, when "
                       "the main computation is right and the model's independent check (often a "
                       "closed form) is the wrong side."))
    false_blocks = gate_false_positives(rows)
    if false_blocks:
        story.append(p(f"{false_blocks} of the <i>blocked</i> attempts were not unsafe code: the "
                       "model used <font face='Courier'>__</font> or <font face='Courier'>___</font> "
                       "as a throwaway loop variable and the gate treated it as a dunder name. "
                       "The benchmark exposed this false positive; it was fixed after the run "
                       "(a name now counts as a dunder only if it has characters other than "
                       "underscores) and a regression test was added. The numbers above are from "
                       "the run before the fix."))
    story.append(figure(figures.per_task(rows, meta["tasks"], FIG / "fig_tasks.png"),
                        "Figure 4. Correct runs out of all runs for each task and arm.",
                        width=TEXT_W * 0.8))
    per_task = {}
    for t in meta["tasks"]:
        group = [r for r in rows if r["task_id"] == t and r["arm"] != "one_shot"]
        per_task[t] = sum(r["correct"] for r in group) / max(len(group), 1)
    easiest = sorted(per_task, key=lambda t: -per_task[t])[:3]
    hardest = sorted(per_task, key=lambda t: per_task[t])[:2]
    story.append(p("Across the loop arms the tasks solved most reliably were "
                   + ", ".join(f"<font face='Courier'>{t}</font> ({pct(per_task[t])})" for t in easiest)
                   + ", while the hardest were "
                   + " and ".join(f"<font face='Courier'>{t}</font> ({pct(per_task[t])})"
                                  for t in hardest)
                   + "." + hard_task_note(rows, hardest)))


def gate_false_positives(rows: list[dict]) -> int:
    """Blocked attempts caused only by names made of underscores (fixed after the benchmark)."""
    count = 0
    for row in rows:
        if "blocked" not in row["failure_kinds"] or not row.get("run_id"):
            continue
        for a in agent_load(row["run_id"])["attempts"]:
            o = a["observation"]
            problems = [ln for ln in o["message"].splitlines() if ln.startswith("- line")]
            if o["kind"] == "blocked" and problems and all(
                    re.search(r"name '_+' is not allowed", ln) for ln in problems):
                count += 1
    return count


def agent_load(run_id: str) -> dict:
    from quantsolve import agent
    return agent.load_trace(run_id)


def model_comparison(story: list, bench: dict) -> None:
    """Final benchmark vs the archived gpt-4o-mini benchmark (same tasks, arms and repeats)."""
    archived = load_json(ROOT / "results" / "archive" / "benchmark_gpt-4o-mini.json")
    if not archived:
        return
    runs = [archived, bench]
    arms = ["one_shot", "quantsolve", "quantsolve+inject", "quantsolve+crash"]
    n = next_table()
    rows = [["Model", "One-shot", "Loop", "Loop + logic bug", "Loop + crash bug",
             "Loop: verified but wrong", "Loop: cost / run (US cents)"]]
    for b in runs:
        s = b["summary"]
        loop = s["quantsolve"]
        rows.append([clean(b["meta"]["model"])]
                    + [f"{s[a]['correct']}/{s[a]['runs']} ({pct(s[a]['accuracy'])})" if a in s else "-"
                       for a in arms]
                    + [f"{loop['verified_but_wrong']}/{loop['runs']}",
                       f"{100 * loop['cost_usd'] / max(loop['runs'], 1):.2f}"])
    old, new = archived["summary"], bench["summary"]
    gain_old = 100 * (old["quantsolve"]["accuracy"] - old["one_shot"]["accuracy"])
    gain_new = 100 * (new["quantsolve"]["accuracy"] - new["one_shot"]["accuracy"])

    def fixed_share(s: dict) -> float:  # share of one-shot errors that the loop removed
        missing = 1 - s["one_shot"]["accuracy"]
        return (s["quantsolve"]["accuracy"] - s["one_shot"]["accuracy"]) / missing if missing else 0.0

    share_old, share_new = fixed_share(old), fixed_share(new)
    vbw_old, vbw_new = old["quantsolve"]["verified_but_wrong"], new["quantsolve"]["verified_but_wrong"]
    story += [p("7.3 Model comparison", H2),
              p(f"The same benchmark (same tasks, arms, prompts and {bench['meta'].get('repeats', 1)} "
                f"repeats) was first run with {clean(archived['meta']['model'])}; those results are "
                "kept in <font face='Courier'>results/archive/</font>. Table "
                f"{n} puts the two models side by side."),
              table(rows, [2.5 * cm, 2.1 * cm, 2.1 * cm, 2.3 * cm, 2.3 * cm, 2.4 * cm,
                           TEXT_W - 13.7 * cm]),
              p(f"Table {n}. Correct runs per arm for both models.", CAPTION),
              p(f"With {clean(archived['meta']['model'])} the loop moved accuracy from "
                f"{pct(old['one_shot']['accuracy'])} to {pct(old['quantsolve']['accuracy'])} "
                f"({gain_old:+.0f} points); with {clean(bench['meta']['model'])} it moved from "
                f"{pct(new['one_shot']['accuracy'])} to {pct(new['quantsolve']['accuracy'])} "
                f"({gain_new:+.0f} points). The raw gain in points is not a fair comparison, "
                "because the weaker model starts with far more room to improve. Measured as the "
                "share of one-shot errors that the loop turned into correct answers, the loop "
                f"removed {pct(share_old)} of the errors with {clean(archived['meta']['model'])} "
                f"and {pct(share_new)} with {clean(bench['meta']['model'])}, and "
                f"{vbw_old} versus {vbw_new} of the {new['quantsolve']['runs']} loop runs ended "
                "verified but wrong. The loop does not add knowledge: it turns a failed check into "
                "another try, and the try only helps if the model can read the observation, find "
                "the real cause, write a correct fix and write checks that would notice a wrong "
                "one. "
                + ("The stronger model did this more often, so the benefit of self-correction "
                   "depends on the capability of the model inside it."
                   if share_new > share_old and vbw_new <= vbw_old else
                   "The two measures do not point the same way here, so this benchmark cannot "
                   "say that the stronger model benefits more.")
                + " Both models are small and each cell rests on few runs, so the exact "
                "percentages are noisy.")]


def hard_task_note(rows: list[dict], hardest: list[str]) -> str:
    group = [r for r in rows if r["task_id"] in hardest and r["arm"] != "one_shot"]
    if not group:
        return ""
    vbw = sum(r["verified"] and not r["correct"] for r in group)
    never = sum(not r["verified"] for r in group)
    return (f" Of the {len(group)} loop-arm runs on these two tasks, {vbw} ended verified but "
            f"wrong (the checks agreed with a wrong computation, so there was no failing "
            f"observation for the loop to react to) and {never} never passed their own checks "
            "within the attempt budget.")


def safety(story: list, report: dict | None) -> None:
    story += [p("8. Safety evaluation", H1)]
    if not report:
        story.append(p("results/safety.json was not found."))
        return
    rows = [["Attack", "Gate", "Outcome", "Contained"]]
    for a in report["attacks"]:
        outcome = f"<i>{a['kind']}</i>: {clean(a['detail'] or a['message'])[:110]}"
        rows.append([clean(a["title"]), "on" if a["gate"] else "off", outcome,
                     "yes" if a["contained"] else "<b>NO</b>"])
    n_gate_off = sum(not a["gate"] for a in report["attacks"])
    t_safety = next_table()
    story += [p(f"<font face='Courier'>safety_eval.py</font> runs {report['total']} attack "
                "programs through the sandbox. Each attack is wrapped in two trivial asserts and "
                "a RESULT, so the only reason for a failure is the attack itself. An attack "
                "counts as contained if the expected defence stopped it and no marker file "
                f"appeared on disk. {n_gate_off} attacks run with the AST gate switched off to "
                "show what the runtime layers do on their own. "
                f"<b>{report['contained']} of {report['total']} attacks were contained.</b>"),
              table(rows, [5.4 * cm, 1.1 * cm, TEXT_W - 8.3 * cm, 1.8 * cm]),
              p(f"Table {t_safety}. Safety evaluation (timeout {report['timeout_s']:g} s for this run).",
                CAPTION),
              p("The last row is the most instructive. With the gate off, a generator frame walk "
                "does escape the restricted builtins and reaches the real <font "
                "face='Courier'>os.environ</font> of the child process; the attack is only "
                "contained because the child scrubbed its environment before running any user "
                "code, so the API key is not there. This is exactly why the restricted <font "
                "face='Courier'>exec()</font> is treated as one layer among several and not as a "
                "security boundary.")]


UI_FIGURES = [
    ("ui_solve.png", "The Solve page after a live run. Left: the example gallery, the problem, the "
     "model, the attempt budget and the demo-bug switch. Right: the run header, the verified "
     "answer with every RESULT value checked against the hand-written reference, and the attempt "
     "timeline (attempt 1 crashed on the injected bug, attempt 2 passed)."),
    ("ui_attempt.png", "One attempt card (Code tab) from the replay of the walkthrough run: the "
     "injected fault is explained in a banner and the failing line is highlighted; the other tabs "
     "hold the Thought, the Observation (traceback) and the Reflection."),
    ("ui_results.png", "The Results page: headline numbers and per-arm charts read from "
     "results/benchmark.json and results/safety.json; further down are the model comparison, a "
     "clickable task-by-arm heatmap, the injected-bug attribution and the safety table."),
    ("ui_history.png", "History: every saved run with search and filters. The coloured squares "
     "show each run's path through its attempts (red: crash, amber: failed self-check, green: "
     "passed)."),
    ("ui_how.png", "How it works: the loop drawn as a diagram, followed on the page by the three "
     "ideas behind it, the six sandbox layers and the failure kinds."),
    ("ui_mobile.png", "The same final answer on a phone-sized screen (390 px wide)."),
]


def screenshots(story: list, replay_id: str | None) -> None:
    items = [(FIG / name, caption) for name, caption in UI_FIGURES if (FIG / name).exists()]
    if not items:
        return
    story += [PageBreak(), p("Appendix A. User interface", H1),
              p("The web application is started with <font face='Courier'>python3 web.py</font> "
                "and served by FastAPI on 127.0.0.1. The front end is a single page written in "
                "plain HTML, CSS and JavaScript (light and dark themes, usable on a phone). When a "
                "problem is submitted the server runs the loop in a background thread and streams "
                "every event (attempt start, action, observation, reflection, final answer) to the "
                "browser over Server-Sent Events, so each step appears as it happens; a Stop "
                "button sets a flag that the loop checks between steps. Saved traces can be "
                "replayed at <font face='Courier'>#/run/&lt;id&gt;</font>. The screenshots below "
                "were taken with headless Chrome driven over the DevTools protocol "
                "(<font face='Courier'>report/capture_ui.py</font>).")]
    for i, (path, caption) in enumerate(items, start=5):
        limit = 520 if i == 5 else 640  # the first one shares its page with the intro text
        width = TEXT_W * (0.5 if path.name == "ui_mobile.png" else 0.98)
        story.append(figure(path, f"Figure {i}. {caption}", width=width, max_height=limit))


def limitations(story: list, bench: dict | None) -> None:
    story += [p("9. Limitations and future work", H1)]
    story += bullets([
        "<b>The sandbox is not a hard security boundary.</b> Restricted <font face='Courier'>"
        "exec()</font> in CPython can be escaped by introspection, which the AST gate blocks by "
        "pattern; a new escape route would get through the gate and would then meet only the "
        "process boundary and the scrubbed environment. For untrusted users a container, a "
        "seccomp/sandbox-exec profile or a WebAssembly Python build would be the right base.",
        "<b>Self-checks are written by the same model.</b> They can be wrong (false alarms that "
        "waste attempts and can stop a correct answer from being accepted) or too weak "
        "(verified but wrong results). Checks generated in a separate call, property-based tests, "
        "or a second model reviewing the checks would make verification more independent.",
        "<b>Small benchmark.</b> Eight problems with " + (
            f"{bench['meta'].get('repeats', 1)} repetition(s)" if bench else "few repetitions")
        + " per case give noisy percentages; differences of one or two runs should not be "
        "over-read. A larger, more varied set would be needed for firm conclusions.",
        "<b>Two small models.</b> The main runs use " + (clean(bench["meta"]["model"]) if bench
        else "one model") + " and the comparison uses the archived gpt-4o-mini run, both chosen "
        "to keep cost low. Larger models would probably make fewer first-attempt errors and write "
        "stronger checks; that was not tested.",
        "<b>Memory limit on macOS</b> is enforced by a watchdog thread that samples peak RSS every "
        "50 ms, so a very fast allocation can overshoot the limit before it is killed.",
        "Future work: generate the checks in a separate call from the problem statement only "
        "(so they cannot copy the program's mistakes), give the model a scratch step to try a "
        "formula on a tiny case before writing the final program, and repeat the benchmark "
        "with more problems, more repetitions and a stronger model."])


def conclusion(story: list, bench: dict | None, safety_report: dict | None) -> None:
    story += [p("10. Conclusion", H1)]
    text = ("QuantSolve implements the lab task end to end: an LLM writes a program for a "
            "quantitative problem, the program runs in a restricted <font face='Courier'>exec()"
            "</font> inside a separate process, failures are classified and returned as cleaned "
            "observations, and Reflexion-style reflections carry lessons from one attempt to the "
            "next. Requiring assert-based self-checks turned some silent logic errors into "
            "visible failures, which is what made healing possible for bugs that do not crash; "
            "Section 7.4 shows that they also let many through.")
    if bench and "one_shot" in bench["summary"] and "quantsolve" in bench["summary"]:
        one, loop = bench["summary"]["one_shot"], bench["summary"]["quantsolve"]
        text += (f" With {clean(bench['meta']['model'])} the loop reached {pct(loop['accuracy'])} "
                 f"accuracy against {pct(one['accuracy'])} for one-shot generation, at roughly "
                 f"{(loop['cost_usd'] / max(one['cost_usd'], 1e-9)):.1f} times the cost.")
        archived = load_json(ROOT / "results" / "archive" / "benchmark_gpt-4o-mini.json")
        if archived:
            o, l = archived["summary"]["one_shot"], archived["summary"]["quantsolve"]
            text += (f" With gpt-4o-mini the same loop went from {pct(o['accuracy'])} to "
                     f"{pct(l['accuracy'])}, so how much self-correction helps depends on how "
                     "well the base model can diagnose and fix its own mistakes.")
    if safety_report:
        text += (f" The sandbox contained {safety_report['contained']} of "
                 f"{safety_report['total']} attacks in the safety evaluation.")
    text += (" The main lesson is that verification is only as good as the checks: the loop "
             "can repair crashes and failed checks, but it cannot repair an error that no check "
             "looks at, and it can be trapped by a check that is itself wrong.")
    story.append(p(text))


def references(story: list) -> None:
    refs = [
        "S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan and Y. Cao. ReAct: Synergizing "
        "Reasoning and Acting in Language Models. ICLR 2023.",
        "N. Shinn, F. Cassano, E. Berman, A. Gopinath, K. Narasimhan and S. Yao. Reflexion: "
        "Language Agents with Verbal Reinforcement Learning. NeurIPS 2023.",
        "L. Gao, A. Madaan, S. Zhou, U. Alon, P. Liu, Y. Yang, J. Callan and G. Neubig. PAL: "
        "Program-aided Language Models. ICML 2023.",
        "W. Chen, X. Ma, X. Wang and W. W. Cohen. Program of Thoughts Prompting: Disentangling "
        "Computation from Reasoning for Numerical Reasoning Tasks. arXiv:2211.12588, 2022 "
        "(TMLR 2023).",
        "A. Madaan, N. Tandon, P. Gupta, S. Hallinan, L. Gao, S. Wiegreffe, U. Alon, N. Dziri, "
        "S. Prabhumoye, Y. Yang, S. Gupta, B. P. Majumder, K. Hermann, S. Welleck, A. Yazdanbakhsh "
        "and P. Clark. Self-Refine: Iterative Refinement with Self-Feedback. NeurIPS 2023.",
        "Python Software Foundation. The Python Standard Library: ast, multiprocessing, resource "
        "and builtins modules. https://docs.python.org/3/library/",
    ]
    story += [p("References", H1)]
    story += [Paragraph(f"[{i}] {clean(r)}", BULLET) for i, r in enumerate(refs, 1)]


# ------------------------------------------------------------------ build

def on_page(canvas, doc) -> None:
    if doc.page == 1:
        return
    canvas.saveState()
    canvas.setFont("Times-Roman", 9)
    canvas.setFillColor(colors.HexColor("#555555"))
    canvas.drawString(2.2 * cm, 1.3 * cm, f"QuantSolve - {AUTHORS}, Batch {STUDENTS[0]['batch']}")
    canvas.drawRightString(A4[0] - 2.2 * cm, 1.3 * cm, f"Page {doc.page}")
    canvas.setStrokeColor(RULE)
    canvas.line(2.2 * cm, A4[1] - 1.5 * cm, A4[0] - 2.2 * cm, A4[1] - 1.5 * cm)
    canvas.drawString(2.2 * cm, A4[1] - 1.3 * cm, COURSE)
    canvas.restoreState()


def build(showcase_id: str | None = None, failure_id: str | None = None,
          silent_id: str | None = None) -> tuple[Path, int, list[str]]:
    FIG.mkdir(parents=True, exist_ok=True)
    figures.loop_diagram(FIG / "fig_loop.png")
    bench = load_json(ROOT / "results" / "benchmark.json")
    safety_report = load_json(ROOT / "results" / "safety.json")
    traces = all_traces()
    showcase = pick_showcase(traces, showcase_id)

    _TABLES["n"] = 2  # Tables 1 and 2 are numbered by hand in the implementation section
    story: list = []
    cover(story, bench["meta"]["model"] if bench else "gpt-4.1-mini")
    aim_objectives(story)
    theory(story)
    architecture(story)
    implementation(story)
    walkthrough(story, showcase)
    silent = pick_silent_case(traces, silent_id)
    unhealed = pick_unhealed_case(traces, failure_id)
    failure_cases(story, silent, unhealed)
    results(story, bench)
    safety(story, safety_report)
    limitations(story, bench)
    conclusion(story, bench, safety_report)
    references(story)
    screenshots(story, showcase['run_id'] if showcase else None)

    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                            topMargin=2.0 * cm, bottomMargin=2.0 * cm, title=TITLE,
                            author=AUTHORS, subject=COURSE)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return OUT, doc.page, [t["run_id"] for t in (showcase, silent, unhealed) if t]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--showcase", help="run id to use for the walkthrough")
    parser.add_argument("--failure-case", help="run id of an unhealed run to discuss")
    parser.add_argument("--silent-case", help="run id of a run whose injected bug passed the checks")
    args = parser.parse_args()
    out, pages, run_ids = build(args.showcase, args.failure_case, args.silent_case)
    print(f"wrote {out} ({pages} pages); walkthrough runs: {', '.join(run_ids)}")
