"""Generate and compile the IEEE-format paper: paper/QuantSolve_IEEE.tex -> paper/QuantSolve_IEEE.pdf

    python3 paper/make_paper.py

Every number in the paper is read from results/*.json, so the text always matches the data in
the repository. Needs pdflatex with the IEEEtran class.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "paper"
REPO = "https://github.com/DeonMenezes-11/QuantSolve"
ARMS = ["one_shot", "quantsolve", "quantsolve+inject", "quantsolve+crash"]
ARM_NAMES = {"one_shot": "One-shot", "quantsolve": "Loop", "quantsolve+inject": "Loop + logic bug",
             "quantsolve+crash": "Loop + crash bug"}
DOMAINS = {"loan_prepay": "Loans", "sip_stepup": "Investing", "income_tax": "Taxation",
           "projectile_drag": "Physics", "birthday": "Probability", "eoq_discount": "Operations",
           "compound_varying": "Interest", "constrained_strings": "Combinatorics"}


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


def tex(s: str) -> str:
    return (s.replace("\\", r"\textbackslash{}").replace("&", r"\&").replace("%", r"\%")
            .replace("_", r"\_").replace("#", r"\#").replace("$", r"\$"))


def pct(x: float) -> str:
    return f"{round(x * 100)}"


def numbers() -> dict[str, str]:
    from quantsolve import tasks  # imported lazily so the script works from any directory

    bench, arch, safety = load("results/benchmark.json"), load("results/archive/benchmark_gpt-4o-mini.json"), load("results/safety.json")
    S, A, meta = bench["summary"], arch["summary"], bench["meta"]
    one, loop, logic, crash = (S[a] for a in ARMS)
    io_l, io_c = logic["inject_outcomes"], crash["inject_outcomes"]
    attributable = io_l.get("caught", 0) + io_l.get("silent", 0) + io_l.get("benign", 0)

    def fixed_share(summary):
        o, l = summary["one_shot"], summary["quantsolve"]
        return round((l["correct"] - o["correct"]) / max(1, o["runs"] - o["correct"]) * 100)

    # Table: main results
    rows = []
    for a in ARMS:
        s = S[a]
        rows.append(f"{ARM_NAMES[a]} & {s['runs']} & {s['correct']} ({pct(s['accuracy'])}\\%) & {s['verified']} & "
                    f"{s['verified_but_wrong']} & {s['avg_attempts']:.2f} & {s['healed']} & {s['cost_usd'] / s['runs'] * 100:.2f} \\\\")
    # Table: model comparison
    comp = []
    for name, summ in ((arch["meta"]["model"], A), (meta["model"], S)):
        cells = " & ".join(f"{summ[a]['correct']}/{summ[a]['runs']}" for a in ARMS)
        comp.append(f"\\texttt{{{name}}} & {cells} & {fixed_share(summ)}\\% \\\\")
    # Table: benchmark problems
    task_rows = []
    per_task = {}
    for r in bench["runs"]:
        key = (r["task_id"], r["arm"])
        c, n = per_task.get(key, (0, 0))
        per_task[key] = (c + int(bool(r["correct"])), n + 1)
    for tid in meta["tasks"]:
        t = tasks.TASKS[tid]
        c, n = per_task.get((tid, "quantsolve"), (0, 0))
        task_rows.append(f"{tex(t.title)} & {DOMAINS.get(tid, '')} & {len(t.keys)} & {c}/{n} \\\\")
    hardest = sorted(meta["tasks"], key=lambda t: per_task.get((t, "quantsolve"), (0, 1))[0] / max(1, per_task.get((t, "quantsolve"), (0, 1))[1]))[:2]
    # Safety breakdown
    att = safety["attacks"]
    gate_blocked = sum(1 for a in att if a["gate"] and a["kind"] == "blocked" and a["contained"])
    timeouts = sum(1 for a in att if a["kind"] == "timeout" and a["contained"])
    memory = sum(1 for a in att if a["gate"] and a["kind"] == "runtime" and a["contained"])
    gate_off = sum(1 for a in att if not a["gate"])

    return {
        "MODEL": meta["model"], "WEAK": arch["meta"]["model"], "REPEATS": str(meta["repeats"]),
        "MAXATT": str(meta["max_attempts"]), "TIMEOUT": f"{meta['timeout_s']:g}", "NTASKS": str(len(meta["tasks"])),
        "NRUNS": str(sum(S[a]["runs"] for a in ARMS)), "NCRASH": str(len(meta.get("crash_tasks", []))),
        "ACC1": pct(one["accuracy"]), "ACCL": pct(loop["accuracy"]), "ACCI": pct(logic["accuracy"]), "ACCC": pct(crash["accuracy"]),
        "C1": str(one["correct"]), "CL": str(loop["correct"]), "R1": str(one["runs"]),
        "GAIN": str(round((loop["accuracy"] - one["accuracy"]) * 100)),
        "ATTL": f"{loop['avg_attempts']:.2f}", "ATTC": f"{crash['avg_attempts']:.2f}",
        "VBW1": str(one["verified_but_wrong"]), "VBWL": str(loop["verified_but_wrong"]), "VBWI": str(logic["verified_but_wrong"]),
        "HEALC": str(crash["healed"]), "RUNSC": str(crash["runs"]), "HEALL": str(loop["healed"]),
        "COSTL": f"{loop['cost_usd'] / loop['runs'] * 100:.2f}", "COST1": f"{one['cost_usd'] / one['runs'] * 100:.2f}",
        "TOKL": f"{round(loop['tokens'] / loop['runs']):,}",
        "TOTALCOST": f"{sum(S[a]['cost_usd'] for a in ARMS):.2f}",
        "WACC1": pct(A["one_shot"]["accuracy"]), "WACCL": pct(A["quantsolve"]["accuracy"]),
        "WVBWL": str(A["quantsolve"]["verified_but_wrong"]),
        "WFIX": str(fixed_share(A)), "SFIX": str(fixed_share(S)),
        "WGAIN": str(round((A["quantsolve"]["accuracy"] - A["one_shot"]["accuracy"]) * 100)),
        "CAUGHT": str(io_l.get("caught", 0)), "SILENT": str(io_l.get("silent", 0)), "BENIGN": str(io_l.get("benign", 0)),
        "ORIGF": str(io_l.get("original_failed", 0)), "NOTAPP": str(io_l.get("not_applied", 0)), "ATTRIB": str(attributable),
        "CCAUGHT": str(io_c.get("caught", 0)), "CORIGF": str(io_c.get("original_failed", 0)),
        "SAFE": str(safety["contained"]), "SAFETOTAL": str(safety["total"]), "SGATE": str(gate_blocked),
        "STIME": str(timeouts), "SMEM": str(memory), "SOFF": str(gate_off),
        "HARD1": tex(tasks.TASKS[hardest[0]].title), "HARD2": tex(tasks.TASKS[hardest[1]].title),
        "MAINROWS": "\n".join(rows), "COMPROWS": "\n".join(comp), "TASKROWS": "\n".join(task_rows),
        "REPO": REPO,
    }


TEMPLATE = r"""\documentclass[conference]{IEEEtran}
\IEEEoverridecommandlockouts
\usepackage{cite}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{array}
\usepackage{multirow}
\usepackage[table]{xcolor}
\usepackage{algorithm}
\usepackage{algpseudocode}
\usepackage[hyphens]{url}
\usepackage[colorlinks=true,linkcolor=black,citecolor=black,urlcolor={blue!70!black},
  pdftitle={QuantSolve: A Self-Verifying, Self-Healing Code-Execution Agent for Quantitative Problems},
  pdfauthor={Deon Menezes, Aishwarya Gawali}]{hyperref}
\graphicspath{{../report/figures/}}
\renewcommand{\algorithmicrequire}{\textbf{Input:}}
\renewcommand{\algorithmicensure}{\textbf{Output:}}

\begin{document}

\title{QuantSolve: A Self-Verifying, Self-Healing Code-Execution Agent for Quantitative Problems Using ReAct and Reflexion}

\author{\IEEEauthorblockN{Deon Menezes}
\IEEEauthorblockA{\textit{Dept. of Artificial Intelligence \& Data Science} \\
\textit{K J Somaiya School of Engineering} \\
\textit{Somaiya Vidyavihar University}, Mumbai, India \\
Roll No. 16014223030}
\and
\IEEEauthorblockN{Aishwarya Gawali}
\IEEEauthorblockA{\textit{Dept. of Artificial Intelligence \& Data Science} \\
\textit{K J Somaiya School of Engineering} \\
\textit{Somaiya Vidyavihar University}, Mumbai, India \\
Roll No. 16014223007}}

\IEEEaftertitletext{\vspace{-0.4\baselineskip}\centering\small
\textbf{GitHub repository (code, data and web application):} \href{<<REPO>>}{\nolinkurl{<<REPO>>}}\par\vspace{1.1\baselineskip}}

\maketitle

\begin{abstract}
Large language models (LLMs) write plausible code quickly, but on multi-step quantitative problems a single sample often contains small slips (an off-by-one loop bound, a flipped sign, a misread rule) that produce a confident but wrong number. We present QuantSolve, an agent that answers such problems through program-aided reasoning inside a self-correction loop. The model writes a complete Python program whose answer must be returned in a \texttt{RESULT} dictionary and verified by at least two \texttt{assert} self-checks that compare quantities computed in different ways. The program runs in a layered sandbox built around a restricted \texttt{exec()} in a separate process. Every failure (blocked code, syntax and runtime errors, failed self-checks, timeouts, contract violations) is returned to the model as a cleaned observation, and a Reflexion-style verbal reflection is stored in memory for later attempts. On <<NTASKS>> problems with hand-written reference answers, run <<REPEATS>> times per arm with \texttt{<<MODEL>>}, the loop raised accuracy from <<ACC1>>\% (one-shot) to <<ACCL>>\% at <<ATTL>> attempts per run on average, and recovered <<HEALC>> of <<RUNSC>> runs with a deliberately injected crash. Injected logic bugs were harder: the model's own self-checks caught <<CAUGHT>> of the <<ATTRIB>> attributable bugs. The sandbox contained all <<SAFETOTAL>> escape and resource-exhaustion attacks we tried. We also describe a web application that streams every step of the loop to the browser in real time.
\end{abstract}

\begin{IEEEkeywords}
large language models, program-aided reasoning, self-correction, ReAct, Reflexion, self-verification, code sandboxing
\end{IEEEkeywords}

\section{Introduction}
Numerical word problems (loan amortisation, step-up investments, income tax with rebates and marginal relief, projectile motion with drag, exact probabilities) are a natural fit for program-aided reasoning: the model describes the computation in code and the interpreter performs the arithmetic~\cite{gao2023pal,chen2023pot}. Code, however, introduces its own failure modes. A program can crash, never terminate, or, worst of all, run to completion and print a wrong number with no visible error.

The lab problem behind this work asks for a \emph{self-correction ``code execution and auto-heal'' loop}: take a complex task, generate Python, execute it safely, capture the traceback on failure and iteratively fix the code. We follow the ReAct pattern of interleaving reasoning, actions and observations~\cite{yao2023react} and the Reflexion idea of improving across trials through verbal self-reflection~\cite{shinn2023reflexion}. Two design choices make the loop useful beyond crash repair. First, every program must verify its own answer with assertions, so that some logic errors surface as observable failures. Second, generated code runs behind several independent defensive layers, because a restricted \texttt{exec()} alone is not a security boundary.

Our contributions are:
\begin{itemize}
\item an execution contract (a \texttt{RESULT} dictionary plus at least two cross-checking assertions) that turns some silent logic errors into observations the loop can act on;
\item a layered sandbox (static AST gate, restricted builtins with a guarded import, a scrubbed child process, CPU and memory limits, a wall-clock timeout) evaluated against <<SAFETOTAL>> attacks;
\item a deterministic fault injector that plants crash or logic bugs in the first attempt, together with an offline attribution procedure that separates bugs the checks caught from bugs that slipped through;
\item a benchmark of <<NTASKS>> problems with hand-written reference solutions, comparing one-shot generation with the loop under two models; and
\item an open-source web application that streams the loop live (\href{<<REPO>>}{\nolinkurl{<<REPO>>}}).
\end{itemize}

\section{Related Work}
\textbf{Reasoning and acting.} ReAct~\cite{yao2023react} interleaves free-text reasoning with tool calls and their observations. In QuantSolve one ReAct step is a whole attempt: the Thought is the model's plan, the Action is a complete program and the Observation is the sandbox result.

\textbf{Learning from feedback.} Reflexion~\cite{shinn2023reflexion} keeps verbal reflections from failed trials in an episodic memory. Self-Refine~\cite{madaan2023selfrefine} uses the model as its own critic, and Self-Debugging~\cite{chen2024selfdebug} shows that execution results and explanations of code improve repair. Huang \emph{et al.}~\cite{huang2024cannot} report that LLMs struggle to self-correct reasoning \emph{without} external feedback. Our loop always grounds correction in an external signal, either the interpreter or a failed assertion.

\textbf{Programs as reasoning.} PAL~\cite{gao2023pal} and Program of Thoughts~\cite{chen2023pot} delegate computation to an interpreter. Weng \emph{et al.}~\cite{weng2023selfverify} show that self-verification improves reasoning. We make verification part of the program itself, as executable assertions.

\textbf{Executing untrusted code.} Benchmarks such as HumanEval run model-written code in isolated environments~\cite{chen2021codex}. We target a lighter, laptop-friendly setting and combine static and runtime defences built on the Python standard library~\cite{pythondocs}.

\section{System Design}
\subsection{The self-healing loop}
Fig.~\ref{fig:loop} and Algorithm~\ref{alg:loop} summarise the loop. Each attempt asks the model, in JSON mode, for a short plan and a complete program. On a failure, a separate reflection call returns a diagnosis, a general lesson and a plan for the next attempt. All lessons so far, together with the previous program and its observation, are passed to the next attempt. A loop guard hashes the normalised abstract syntax tree (AST) of each program and records an error signature (failure kind, exception type and failing source line). When either repeats, the next prompt carries an explicit ``change approach'' nudge at a higher sampling temperature. When a program passes, a final call writes a plain-English answer that quotes the verified \texttt{RESULT} without recomputing it.

\begin{figure*}[t]
\centering
\includegraphics[width=0.86\textwidth]{ui_diagram.png}
\caption{The QuantSolve loop as drawn in the web application. Blue: normal flow. Red: a failure that becomes the observation for the next attempt. Green: all self-checks passed. A reflection is stored in memory after every failure and shown to every later attempt.}
\label{fig:loop}
\end{figure*}

\begin{algorithm}[t]
\caption{QuantSolve self-healing loop}
\label{alg:loop}
\small
\begin{algorithmic}[1]
\Require task $T$, attempt budget $K$, optional fault mode $f$
\Ensure verified \texttt{RESULT} and answer, or failure
\State $M \gets [\,]$ \Comment{Reflexion memory}
\For{$k = 1$ \textbf{to} $K$}
  \State $(\text{thought}, c) \gets \textsc{Solve}(T, c_{k-1}, o_{k-1}, M)$
  \State \textbf{if} $k = 1$ \textbf{and} $f \neq \varnothing$ \textbf{then} $c \gets \textsc{Inject}(c, f)$
  \State $o_k \gets \textsc{Sandbox}(c)$ \Comment{gate, child process, checks}
  \State \textbf{if} $o_k.\text{ok}$ \textbf{then return} $\textsc{Summarise}(T, o_k.\texttt{RESULT})$
  \State $M \gets M \cup \{\textsc{Reflect}(T, c, o_k, M)\}$
\EndFor
\State \Return failure with the last observation
\end{algorithmic}
\end{algorithm}

\subsection{Execution contract and self-verification}
A program must compute every number from the task, store exactly the requested keys in a JSON-serialisable \texttt{RESULT} dictionary, and contain at least two assertions. Each assertion must compare quantities obtained in \emph{different} ways, for example a month-by-month amortisation against the closed-form interest total, or a dynamic-programming count against \emph{total minus complement}. Floats must be compared with a tolerance. Programs with fewer than two assertions are rejected before they run. Every outcome is classified into one of six failure kinds (\emph{blocked}, \emph{syntax}, \emph{runtime}, \emph{assertion}, \emph{timeout}, \emph{contract}), and tracebacks are trimmed to the frames of the generated program, with each source line attached.

\subsection{Layered sandbox}
\emph{(1) Static AST gate.} Imports are limited to an allow-list (\texttt{math}, \texttt{statistics}, \texttt{fractions}, \texttt{decimal}, \texttt{itertools}, \texttt{numpy} and a few others). The names \texttt{eval}, \texttt{exec}, \texttt{open}, \texttt{getattr}, \texttt{\_\_import\_\_} and similar are rejected, along with every attribute that starts with an underscore and attributes that lead out of the sandbox (frame internals, re-exported modules, NumPy file I/O). \emph{(2) Restricted builtins} with a guarded \texttt{\_\_import\_\_} that re-checks the allow-list at run time. \emph{(3) A fresh \texttt{multiprocessing} child} (``spawn'' start method) that wipes its environment before running user code, so the API key is never present. \emph{(4) Resource limits}: \texttt{RLIMIT\_CPU} and a 1~GB memory watchdog. \emph{(5) A wall-clock timeout} (<<TIMEOUT>>~s by default), after which the child is terminated.

\subsection{Fault injection and attribution}
To demonstrate and measure healing, an optional injector rewrites the first program with an \texttt{ast.NodeTransformer}. \emph{Crash} mode misspells one use of a variable, which raises a \texttt{NameError}. \emph{Logic} mode makes the first \texttt{range()} loop stop one step early or flips a \texttt{+}/\texttt{-} inside a loop. Because the injection happens after the model has written its code, an attempt-1 failure does not prove that the checks caught the injected bug. We therefore re-run the model's original program offline and label each case \emph{caught} (the original passes but the mutant fails), \emph{silent} (both pass with different numbers), \emph{benign} (identical numbers), \emph{original failed}, or \emph{not applied}.

\subsection{Web application}
A FastAPI server exposes a JSON API and runs each solve in a background thread. The loop's event callback appends to a per-job log, which is streamed to the browser as Server-Sent Events~\cite{whatwgsse} (\emph{attempt start}, \emph{action}, \emph{observation}, \emph{reflection}, \emph{final}). Because the log can be replayed from any position, a page refresh resumes a running job, and a stop flag is checked between steps. The front end is a hand-written single-page application without a framework. It provides a pipeline stepper that shows where each attempt failed, per-attempt tabs (Thought, Code, Observation, Reflection) with the failing and injected lines highlighted and a diff against the previous attempt, a history of saved runs, benchmark dashboards and an explainer (Figs.~\ref{fig:solve}--\ref{fig:attempt}). The server binds to the local host only, and model output is always rendered as text, never as HTML.

\begin{figure*}[t]
\centering
\includegraphics[width=0.53\textwidth]{ui_solve.png}\hspace{0.04\textwidth}
\includegraphics[width=0.215\textwidth]{ui_mobile.png}
\caption{Left: the Solve page after a live run (example gallery and options on the left; run header, verified answer checked against the reference, attempt timeline and Reflexion memory on the right). Right: the same answer on a 390-pixel-wide phone screen.}
\label{fig:solve}
\end{figure*}

\begin{figure*}[t]
\centering
\includegraphics[width=0.49\textwidth]{ui_results.png}\hfill
\includegraphics[width=0.49\textwidth]{ui_history.png}
\caption{Left: the results dashboard, which reads the benchmark and safety files. Right: the run history with search and filters; each square is one attempt (red: crash, amber: failed self-check, green: passed).}
\label{fig:dash}
\end{figure*}

\section{Experimental Setup}
\textbf{Problems.} Table~\ref{tab:tasks} lists the <<NTASKS>> problems. Each states every rule and the exact \texttt{RESULT} keys, and has a hand-written reference solution cross-checked by an independent method in the test suite. A run is \emph{correct} only if every scored key is within its tolerance of the reference.

\textbf{Arms.} \emph{One-shot} allows a single attempt. \emph{Loop} is the full system with $K{=}<<MAXATT>>$ attempts. \emph{Loop + logic bug} injects a logic fault into attempt~1. \emph{Loop + crash bug} injects a crash fault on <<NCRASH>> problems. Every case was repeated <<REPEATS>> times with \texttt{<<MODEL>>}~\cite{openaimodels}, giving <<NRUNS>> runs in total for an estimated US\$<<TOTALCOST>>. The same benchmark was first run with \texttt{<<WEAK>>}.

\textbf{Metrics.} \emph{Accuracy} against the reference, \emph{verified} (the final program passed its own checks), \emph{verified but wrong}, attempts per run, \emph{healed} (attempt~1 failed and a later attempt passed), and cost estimated from token counts.

\begin{table}[t]
\centering
\caption{Benchmark problems and correct loop runs}
\label{tab:tasks}
\footnotesize
\begin{tabular}{@{}p{3.85cm}lcc@{}}
\toprule
Problem & Domain & Keys & Loop \\
\midrule
<<TASKROWS>>
\bottomrule
\end{tabular}
\end{table}

\section{Results}
\subsection{Does the loop help?}
Table~\ref{tab:main} and Fig.~\ref{fig:arms} give the main results. With \texttt{<<MODEL>>}, the loop raised accuracy from <<ACC1>>\% to <<ACCL>>\% (+<<GAIN>> points) and used only <<ATTL>> attempts per run on average, because most first programs already passed. A loop run cost <<COSTL>>~US cents, compared with <<COST1>> for one-shot. In the one-shot arm most failures were failed assertions, which is exactly the signal the loop exploits. On the other hand, <<VBWL>> loop runs ended \emph{verified but wrong}: they passed their own checks yet disagreed with the reference. The weakest problems were \emph{<<HARD1>>} and \emph{<<HARD2>>}, where the checks tended to agree with an incorrect method.

\begin{table}[t]
\centering
\caption{Benchmark summary (<<MODEL>>, $K{=}<<MAXATT>>$)}
\label{tab:main}
\footnotesize
\setlength{\tabcolsep}{3.2pt}
\begin{tabular}{@{}lccccccc@{}}
\toprule
Arm & Runs & Correct & Verif. & V.\,wrong & Att. & Healed & \textcent/run \\
\midrule
<<MAINROWS>>
\bottomrule
\end{tabular}
\end{table}

\begin{figure}[t]
\centering
\includegraphics[width=\columnwidth]{fig_arms.png}
\caption{Accuracy, average attempts and average cost per run for each arm.}
\label{fig:arms}
\end{figure}

\subsection{Injected bugs}
Crash faults are easy to repair. The cleaned traceback names the line and often suggests the correct identifier, and <<HEALC>> of <<RUNSC>> crash runs recovered (<<ACCC>>\% correct, <<ATTC>> attempts). Logic faults expose the limits of self-written checks (Table~\ref{tab:attr}). Of the <<ATTRIB>> logic faults that could be attributed, the checks caught <<CAUGHT>>, <<SILENT>> changed the answer while every check still passed, and <<BENIGN>> did not change the answer. In the remaining runs the model's own program had already failed (<<ORIGF>>) or the injector found nothing to mutate (<<NOTAPP>>). The logic-bug arm therefore ends with <<VBWI>> verified-but-wrong runs and <<ACCI>>\% accuracy.

\begin{table}[t]
\centering
\caption{Attribution of attempt-1 outcomes in the injected arms}
\label{tab:attr}
\footnotesize
\setlength{\tabcolsep}{3.5pt}
\begin{tabular}{@{}lccccc@{}}
\toprule
Arm & Caught & Silent & Benign & Orig.\ failed & N/A \\
\midrule
Loop + logic bug & <<CAUGHT>> & <<SILENT>> & <<BENIGN>> & <<ORIGF>> & <<NOTAPP>> \\
Loop + crash bug & <<CCAUGHT>> & 0 & 0 & <<CORIGF>> & 0 \\
\bottomrule
\end{tabular}
\end{table}

\subsection{Effect of the base model}
Table~\ref{tab:models} compares the two models on the same benchmark. With \texttt{<<WEAK>>} the loop moved accuracy from <<WACC1>>\% to <<WACCL>>\% (+<<WGAIN>> points), but <<WVBWL>> of its loop runs were verified but wrong. Raw point gains favour the weaker model only because it starts lower. Measured as the share of one-shot errors that the loop fixed, the gain was <<WFIX>>\% for \texttt{<<WEAK>>} and <<SFIX>>\% for \texttt{<<MODEL>>}. Self-correction adds no knowledge. It turns a failed check into another attempt, and that attempt helps only if the model can read the observation, find the cause and write a correct fix.

\begin{table}[t]
\centering
\caption{Correct runs per arm for both models}
\label{tab:models}
\footnotesize
\setlength{\tabcolsep}{3.2pt}
\begin{tabular}{@{}lccccc@{}}
\toprule
Model & One-shot & Loop & +Logic & +Crash & Errors fixed \\
\midrule
<<COMPROWS>>
\bottomrule
\end{tabular}
\end{table}

\subsection{Per-problem behaviour and safety}
Fig.~\ref{fig:tasks} breaks the results down by problem. Finance, tax, physics and inventory problems were solved reliably, while exact combinatorics remained hard in every arm. In the safety evaluation all <<SAFE>> of <<SAFETOTAL>> attack programs were contained: <<SGATE>> were rejected by the AST gate, <<STIME>> were stopped by the timeout and <<SMEM>> by the memory watchdog. The remaining <<SOFF>> were run with the gate disabled on purpose. These showed that the restricted builtins, the guarded import and the environment scrub still hold on their own. In one of them a generator frame walk reached the real \texttt{os.environ} of the child process, but found no key there.

\begin{figure}[t]
\centering
\includegraphics[width=\columnwidth]{fig_tasks.png}
\caption{Correct runs out of all runs for each problem and arm.}
\label{fig:tasks}
\end{figure}

\section{The Web Application}
Fig.~\ref{fig:solve} shows the Solve page after a live run on the income-tax problem with the crash fault enabled. Attempt~1 failed with a \texttt{NameError} on the injected line, the reflection was stored in memory, and attempt~2 passed all of its checks. Every value is marked against the reference answer. Fig.~\ref{fig:dash} shows the results dashboard and the run history, where coloured squares trace each run's path through its attempts, and Fig.~\ref{fig:attempt} shows an attempt card with the injected fault and the failing assertion highlighted. The interface supports light and dark themes and adapts to phone screens.





\begin{figure}[t]
\centering
\includegraphics[width=\columnwidth]{ui_attempt.png}
\caption{An attempt card (Code tab) from a replayed run. The injected off-by-one is explained in a banner, the mutated line is marked in amber and the failing assertion in red.}
\label{fig:attempt}
\end{figure}

\section{Discussion and Limitations}
\textbf{Self-written checks share the model's blind spots.} Assertions turned some silent errors into observable failures, but most injected logic bugs that changed the answer still passed the checks. Checks can also be wrong themselves, which wastes attempts. Generating the checks in a separate call from the problem statement alone, using property-based tests, or having a second model review the checks would make verification more independent.

\textbf{The sandbox is defence in depth, not a hard boundary.} Restricted \texttt{exec()} in CPython can be escaped by introspection, which the AST gate blocks by pattern. Any unknown escape would then meet only the process boundary and the scrubbed environment. For untrusted users a container, an OS sandbox profile or a WebAssembly build of Python would be the right base.

\textbf{Small benchmark.} With <<NTASKS>> problems and <<REPEATS>> repeats per case, differences of one or two runs should not be over-read. Larger models were not tested, to keep the cost low.

\section{Conclusion}
QuantSolve implements a complete self-correction loop for quantitative problems: program-aided reasoning, an execution contract with self-verifying assertions, a layered sandbox, Reflexion memory and a live web interface. The loop improved accuracy at roughly the cost of one extra model call per failure, and it repaired injected crashes reliably. It is only as good as the checks, though. It can repair crashes and failed checks, but it cannot repair an error that no check looks at. The code, results, traces and web application are available at \href{<<REPO>>}{\nolinkurl{<<REPO>>}}.

\section*{Code Availability}
The source code, benchmark traces, results and the web application are openly available at \href{<<REPO>>}{\nolinkurl{<<REPO>>}}. The command \texttt{python3 web.py} starts the website, and \texttt{python3 -m pytest} runs the offline test suite.

\IEEEtriggeratref{7}  % balance the two columns on the last page
\begin{thebibliography}{00}
\bibitem{yao2023react} S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan, and Y. Cao, ``ReAct: Synergizing reasoning and acting in language models,'' in \emph{Proc. Int. Conf. Learn. Represent. (ICLR)}, 2023.
\bibitem{shinn2023reflexion} N. Shinn, F. Cassano, A. Gopinath, K. Narasimhan, and S. Yao, ``Reflexion: Language agents with verbal reinforcement learning,'' in \emph{Adv. Neural Inf. Process. Syst. (NeurIPS)}, 2023.
\bibitem{gao2023pal} L. Gao, A. Madaan, S. Zhou, U. Alon, P. Liu, Y. Yang, J. Callan, and G. Neubig, ``PAL: Program-aided language models,'' in \emph{Proc. Int. Conf. Mach. Learn. (ICML)}, 2023.
\bibitem{chen2023pot} W. Chen, X. Ma, X. Wang, and W. W. Cohen, ``Program of thoughts prompting: Disentangling computation from reasoning for numerical reasoning tasks,'' \emph{Trans. Mach. Learn. Res.}, 2023.
\bibitem{madaan2023selfrefine} A. Madaan \emph{et al.}, ``Self-Refine: Iterative refinement with self-feedback,'' in \emph{Adv. Neural Inf. Process. Syst. (NeurIPS)}, 2023.
\bibitem{chen2024selfdebug} X. Chen, M. Lin, N. Sch\"arli, and D. Zhou, ``Teaching large language models to self-debug,'' in \emph{Proc. Int. Conf. Learn. Represent. (ICLR)}, 2024.
\bibitem{huang2024cannot} J. Huang, X. Chen, S. Mishra, H. S. Zheng, A. W. Yu, X. Song, and D. Zhou, ``Large language models cannot self-correct reasoning yet,'' in \emph{Proc. Int. Conf. Learn. Represent. (ICLR)}, 2024.
\bibitem{weng2023selfverify} Y. Weng, M. Zhu, F. Xia, B. Li, S. He, S. Liu, B. Sun, K. Liu, and J. Zhao, ``Large language models are better reasoners with self-verification,'' in \emph{Findings Assoc. Comput. Linguist.: EMNLP}, 2023.
\bibitem{chen2021codex} M. Chen \emph{et al.}, ``Evaluating large language models trained on code,'' \emph{arXiv preprint arXiv:2107.03374}, 2021.
\bibitem{pythondocs} Python Software Foundation, ``The Python standard library: \texttt{ast}, \texttt{multiprocessing} and \texttt{resource},'' Python 3.13 documentation. [Online]. Available: \url{https://docs.python.org/3/library/}
\bibitem{whatwgsse} WHATWG, ``Server-sent events,'' \emph{HTML Living Standard}. [Online]. Available: \url{https://html.spec.whatwg.org/multipage/server-sent-events.html}
\bibitem{openaimodels} OpenAI, ``Models,'' OpenAI API documentation. [Online]. Available: \url{https://platform.openai.com/docs/models}
\end{thebibliography}

\end{document}
"""


def build() -> Path:
    import sys
    sys.path.insert(0, str(ROOT))
    text = TEMPLATE
    for key, value in numbers().items():
        text = text.replace(f"<<{key}>>", value)
    assert "<<" not in text, "unfilled placeholder"
    src = PAPER / "QuantSolve_IEEE.tex"
    src.write_text(text)
    for _ in range(2):  # second pass resolves references
        proc = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", src.name],
                              cwd=PAPER, capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout[-3000:])
            raise SystemExit("pdflatex failed")
    for ext in (".aux", ".log", ".out"):
        (PAPER / f"QuantSolve_IEEE{ext}").unlink(missing_ok=True)
    return PAPER / "QuantSolve_IEEE.pdf"


if __name__ == "__main__":
    print(f"wrote {build()}")
