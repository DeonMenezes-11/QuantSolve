"""Build docs/QuantSolve_Explained.pdf: a short, plain-English explanation of the project.

    python3 docs/build_explainer.py

Numbers come from results/*.json and the walkthrough from a saved trace in runs/, so the
document always matches the data in the repository.
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "report" / "figures"
OUT = ROOT / "docs" / "QuantSolve_Explained.pdf"
REPO = "https://github.com/DeonMenezes-11/QuantSolve"
WALKTHROUGH = "20261006-024806_income_tax_inject-crash"

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#475569")
ACCENT = colors.HexColor("#4f46e5")
TEAL = colors.HexColor("#0d9488")
SOFT = colors.HexColor("#eef0ff")
RULE = colors.HexColor("#dfe3ee")
PAGE_W, PAGE_H = A4
MARGIN = 1.7 * cm
TEXT_W = PAGE_W - 2 * MARGIN

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.6, leading=13.6, textColor=INK, spaceAfter=5)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.4, leading=11.4, textColor=MUTED, spaceAfter=0)
H1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=ACCENT,
                    spaceBefore=9, spaceAfter=4)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.6, leading=11.4, spaceAfter=0)
CELL_B = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")
STEP = ParagraphStyle("step", parent=BODY, leftIndent=14, firstLineIndent=-14, spaceAfter=3.5)
CAPTION = ParagraphStyle("cap", parent=SMALL, alignment=TA_LEFT, spaceBefore=3, spaceAfter=6)


def p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def code(text: str) -> str:
    return f"<font face='Courier' size='8.6'>{text}</font>"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def fmt_in(n: float) -> str:
    """Indian digit grouping (2,31,400)."""
    s = str(int(n))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])


def image(name: str, width: float) -> Image:
    from PIL import Image as PILImage
    with PILImage.open(FIG / name) as im:
        w, h = im.size
    return Image(str(FIG / name), width=width, height=width * h / w)


def table(rows, widths, header=True, zebra=True) -> Table:
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4.5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5), ("LEFTPADDING", (0, 0), (-1, -1), 6),
             ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    if zebra:
        style += [("BACKGROUND", (0, r), (-1, r), colors.HexColor("#f6f7fb")) for r in range(2, len(rows), 2)]
    t.setStyle(TableStyle(style))
    return t


def header_block() -> list:
    title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=21, leading=25, textColor=INK)
    sub = ParagraphStyle("s", fontName="Helvetica", fontSize=10.5, leading=14, textColor=MUTED)
    meta = ParagraphStyle("m", fontName="Helvetica", fontSize=8.8, leading=12, textColor=INK)
    band = Table([[p("QuantSolve, explained", title)],
                  [p("What the project does, how one run works, and what we measured", sub)],
                  [p("<b>Deon Menezes</b> (16014223030) &nbsp;·&nbsp; <b>Aishwarya Gawali</b> (16014223007) "
                     "&nbsp;·&nbsp; Batch B1 &nbsp;·&nbsp; Generative AI Laboratory, Lab CA<br/>"
                     f"Code: <link href='{REPO}' color='#4f46e5'><u>{REPO}</u></link>", meta)]],
                 colWidths=[TEXT_W])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("LEFTPADDING", (0, 0), (-1, -1), 14),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 14), ("TOPPADDING", (0, 0), (0, 0), 13),
                              ("BOTTOMPADDING", (0, -1), (-1, -1), 12), ("LINEBEFORE", (0, 0), (0, -1), 4, ACCENT)]))
    return [band, Spacer(1, 8)]


def build() -> tuple[Path, int]:
    bench = load(ROOT / "results" / "benchmark.json")
    archive = load(ROOT / "results" / "archive" / "benchmark_gpt-4o-mini.json")
    safety = load(ROOT / "results" / "safety.json")
    run = load(ROOT / "runs" / f"{WALKTHROUGH}.json")
    S, model = bench["summary"], bench["meta"]["model"]
    one, loop, logic, crash = S["one_shot"], S["quantsolve"], S["quantsolve+inject"], S["quantsolve+crash"]
    a1, a2 = run["attempts"][0], run["attempts"][-1]
    res = run["result"]
    io = logic["inject_outcomes"]
    attributable = io.get("caught", 0) + io.get("silent", 0) + io.get("benign", 0)

    story: list = header_block()

    story += [p("1. What QuantSolve is", H1),
              p("QuantSolve answers multi-step <b>numbers questions</b> (loans, investments, income tax, physics, "
                "probability, inventory, counting). Instead of asking a language model for the number directly, "
                "it asks the model to <b>write a Python program</b> that computes the answer. The program runs in a "
                "locked-down <b>sandbox</b>, it has to <b>check its own answer</b> with at least two "
                f"{code('assert')} statements, and when anything goes wrong the model <b>reads the error, writes "
                "down a lesson and tries again</b>, up to five attempts. The answer you get back is therefore one "
                "that came out of code which actually ran and passed its own checks."),
              p("2. Why we built it this way", H1),
              p("Language models write code that looks right but often contains small slips: a loop that stops "
                "one step early, a flipped sign, a rule from the question applied in the wrong order. A single "
                "attempt hides those slips. Running the code gives an objective signal (the interpreter does not "
                "care how confident the model sounded), and feeding that signal back lets the model repair its "
                "own work. This is the <b>Self-Correction \"Code Execution &amp; Auto-Heal\" loop</b> from the lab "
                "brief, built on two published ideas: <b>ReAct</b> (reason, act, observe) and <b>Reflexion</b> "
                "(learn from failures through written self-reflection)."),
              p("3. The loop in one picture", H1),
              KeepTogether([image("ui_diagram.png", TEXT_W),
                            p("Blue arrows are the normal flow and red arrows are failures, which become the "
                              "observation for the next attempt. A lesson is stored after every failure and "
                              "shown to every later attempt. Green means every self-check passed.", CAPTION)])]

    story += [p("4. One real run, step by step", H1),
              p(f"Run {code(WALKTHROUGH)}: income tax under India's new regime (FY 2024-25) for three salaries, "
                "with the <i>crash</i> demo switch on, so QuantSolve deliberately breaks the first program to show "
                "the repair.")]
    steps = [
        ("Thought + Action.", f"The model plans the method (taxable income, slab rates, rebate under 87A, "
         f"marginal relief, 4% cess) and writes a {len(a1['code'].splitlines())}-line program that stores the "
         f"answer in {code('RESULT')} and contains {a1['observation'].get('asserts', 0)} self-checks."),
        ("Demo bug.", "QuantSolve renames one use of " + code("standard_deduction") + " to "
         + code("standard_deductino") + f" on line {a1['observation'].get('line')}, exactly as a typo would."),
        ("Observation.", f"The sandbox reports a <b>{a1['observation'].get('exc_type')}</b> on line "
         f"{a1['observation'].get('line')}, with a traceback trimmed to the program's own lines."),
        ("Reflection.", f"The model writes: <i>\"{a1['reflection']['reflection']}\"</i> This lesson is kept in memory."),
        ("Attempt 2.", f"The program is rewritten with the fix. All {a2['observation'].get('asserts', 0)} self-checks "
         f"pass and the answer matches the hand-written reference: tax A = Rs {fmt_in(res['tax_a'])}, tax B = "
         f"Rs {fmt_in(res['tax_b'])}, tax C = Rs {fmt_in(res['tax_c'])}, effective rate {res['effective_rate_c_pct']}%."
         f" The whole run took {run['duration_s']:.0f} s and cost about ${run['usage']['cost_usd']:.4f}."),
    ]
    story += [p(f"<b>{i}. {head}</b> {text}", STEP) for i, (head, text) in enumerate(steps, 1)]

    concept_rows = [[p("<b>Idea</b>", CELL_B), p("<b>What it means</b>", CELL_B), p("<b>Where it lives in QuantSolve</b>", CELL_B)],
                    [p("<b>ReAct</b>", CELL), p("Reason (Thought), act (Action), look at the result (Observation), repeat.", CELL),
                     p("Each attempt = a plan, a full program, and the sandbox result.", CELL)],
                    [p("<b>Reflexion</b>", CELL), p("After a failure, write a short lesson and remember it.", CELL),
                     p("A separate call returns diagnosis, lesson and next plan; all lessons go into every later prompt.", CELL)],
                    [p("<b>Self-verification</b>", CELL), p("The program checks its own answer.", CELL),
                     p("At least two asserts comparing quantities computed two ways (loop vs formula, parts vs total).", CELL)],
                    [p("<b>Program-aided reasoning</b>", CELL), p("Let Python do the arithmetic.", CELL),
                     p("The model never states the final number; the program computes it.", CELL)],
                    [p("<b>Sandboxing</b>", CELL), p("Run untrusted code without risk.", CELL),
                     p("AST safety gate, restricted builtins, guarded import, separate process with no API key, CPU and memory limits, timeout.", CELL)]]
    story += [p("5. The ideas behind it", H1),
              table(concept_rows, [3.3 * cm, 5.4 * cm, TEXT_W - 8.7 * cm]),
              Spacer(1, 4),
              p(f"The sandbox was attacked with {safety['total']} escape and resource-exhaustion programs (shell "
                "commands, reading system files, introspection tricks, infinite loops, memory bombs, reading the API "
                f"key). <b>All {safety['contained']} were contained.</b> Three of them ran with the static gate switched "
                "off on purpose, to show that the runtime layers hold on their own.")]

    site_rows = [[p("<b>Solve</b>: pick one of eight examples or type a problem, choose the model, the attempt "
                    "budget and an optional demo bug, then watch every attempt stream in live with its Thought, "
                    "Code (failing line highlighted), Observation and Reflection.", CELL)],
                 [p("<b>History</b>: every saved run, searchable; coloured squares show each run's path "
                    "(crash, then fixed, and so on).", CELL)],
                 [p("<b>Run replay</b>: any saved run, with a shareable link.", CELL)],
                 [p("<b>Results</b>: the benchmark numbers, charts, model comparison and safety table.", CELL)],
                 [p("<b>How it works</b>: the diagram above, the ideas and the sandbox layers.", CELL)]]
    site = Table(site_rows, colWidths=[TEXT_W * 0.47])
    site.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                              ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    shot = image("ui_solve.png", TEXT_W * 0.5)
    two_col = Table([[site, shot]], colWidths=[TEXT_W * 0.49, TEXT_W * 0.51])
    two_col.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [p("6. The website", H1),
              p(f"Started with {code('python3 web.py')}; it runs on your own machine at "
                f"{code('http://127.0.0.1:8503')}. It is a hand-built single-page site (FastAPI on the server, plain "
                "HTML, CSS and JavaScript in the browser) with light and dark themes, and it works on a phone."),
              two_col,
              p("Right: the Solve page after the run described in Section 4.", CAPTION)]

    def pct(s):
        return f"{round(s['accuracy'] * 100)}% ({s['correct']}/{s['runs']})"

    a_one, a_loop = archive["summary"]["one_shot"], archive["summary"]["quantsolve"]
    findings = [[p("<b>Setting</b>", CELL_B), p(f"<b>Correct answers ({model})</b>", CELL_B), p("<b>What it shows</b>", CELL_B)],
                [p("One attempt, no healing", CELL), p(pct(one), CELL), p("The baseline.", CELL)],
                [p("The full loop", CELL), p(pct(loop), CELL),
                 p(f"Healing raises accuracy by {round((loop['accuracy'] - one['accuracy']) * 100)} points, using "
                   f"{loop['avg_attempts']:.2f} attempts on average.", CELL)],
                [p("Loop + injected crash", CELL), p(pct(crash), CELL),
                 p(f"Crashes are easy to repair: {crash['healed']} of {crash['runs']} runs recovered.", CELL)],
                [p("Loop + injected logic bug", CELL), p(pct(logic), CELL),
                 p(f"Harder: the self-checks caught {io.get('caught', 0)} of {attributable} logic bugs that could be "
                   "traced; the rest slipped through or changed nothing.", CELL)],
                [p("Weaker model (gpt-4o-mini)", CELL),
                 p(f"{round(a_one['accuracy'] * 100)}% → {round(a_loop['accuracy'] * 100)}%", CELL),
                 p("The loop helps, but how much depends on how well the model can debug itself.", CELL)]]
    story += [p("7. What we measured", H1),
              p(f"Eight problems with hand-written reference answers, each run {bench['meta']['repeats']} times per "
                f"setting, at most {bench['meta']['max_attempts']} attempts. A run counts as correct only if every value "
                "matches the reference within tolerance."),
              table(findings, [4.2 * cm, 4.1 * cm, TEXT_W - 8.3 * cm]),
              Spacer(1, 5),
              p(f"A loop run cost about <b>${loop['cost_usd'] / loop['runs']:.4f}</b> on average. The honest "
                "limitation: checks written by the same model can share its blind spots, so a program can pass "
                "its own checks and still be wrong. That is why every sample problem is also scored against an "
                "independent reference answer."),
              p("8. Try it", H1),
              p(f"{code('pip install -r requirements.txt')} &nbsp;→&nbsp; put an OpenAI key in {code('.env')} "
                f"&nbsp;→&nbsp; {code('python3 web.py')} for the website, or {code('python3 cli.py run-task income_tax --inject crash')} "
                f"in a terminal. {code('python3 -m pytest')} runs the offline test suite. Full code, results and the "
                f"reports: <link href='{REPO}' color='#4f46e5'><u>{REPO}</u></link>")]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.8)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 1.0 * cm, "QuantSolve · Deon Menezes & Aishwarya Gawali · Generative AI Laboratory, Lab CA")
        canvas.drawRightString(PAGE_W - MARGIN, 1.0 * cm, f"{doc.page}")
        canvas.restoreState()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=1.5 * cm,
                            bottomMargin=1.6 * cm, title="QuantSolve, explained",
                            author="Deon Menezes, Aishwarya Gawali", subject="Generative AI Laboratory, Lab CA")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return OUT, doc.page


if __name__ == "__main__":
    out, pages = build()
    print(f"wrote {out} ({pages} pages)")
