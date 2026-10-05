"""Matplotlib figures for the report. Every number comes from the results files."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

NAVY = "#1f3a5f"
INK = "#2b2b2b"
MUTED = "#6b6b6b"
GRID = "#e4e4e0"
# fixed categorical order (validated reference palette, light mode): colour follows the arm
ARM_COLORS = {"one_shot": "#2a78d6", "quantsolve": "#eb6834",
              "quantsolve+inject": "#1baf7a", "quantsolve+crash": "#eda100"}
ARM_LABELS = {"one_shot": "one-shot", "quantsolve": "loop",
              "quantsolve+inject": "loop + logic bug", "quantsolve+crash": "loop + crash bug"}
KINDS = ["blocked", "syntax", "runtime", "assertion", "timeout", "contract"]
BLUES = LinearSegmentedColormap.from_list("blues", ["#f4f8fd", "#86b6ef", "#256abf", "#0d366b"])

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": MUTED,
    "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 100,
})


def _save(fig, path: Path) -> Path:
    fig.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def loop_diagram(path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10.8, 4.3))
    ax.set_xlim(0, 10.8)
    ax.set_ylim(0, 4.3)
    ax.axis("off")

    def box(x, y, text, w=1.5, h=0.9, fill="#eef3f9", edge=NAVY, dashed=False):
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                    boxstyle="round,pad=0.02,rounding_size=0.08",
                                    facecolor=fill, edgecolor=edge, linewidth=1.3,
                                    linestyle="--" if dashed else "-"))
        ax.text(x, y, text, ha="center", va="center", fontsize=7.8, color=INK)

    def arrow(a, b, color=NAVY):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=11, color=color,
                                     linewidth=1.2))

    def note(x, y, text, color=MUTED):
        ax.text(x, y, text, ha="center", va="center", fontsize=7.2, color=color, style="italic")

    top, low = 3.25, 1.05
    xs = [0.85, 2.67, 4.49, 6.31, 8.13, 9.95]
    labels = ["Task\n(natural language)", "Thought + Action\nLLM writes program\n(JSON mode)",
              "Fault injector\nattempt 1 only\n(demo switch)", "AST safety gate\nimports, names,\nattributes",
              "Child process\nrestricted exec()\nCPU, memory, time", "Contract check\nRESULT dict and\n>= 2 asserts"]
    for i, (x, label) in enumerate(zip(xs, labels)):
        box(x, top, label, dashed=(i == 2), fill="#fff7e6" if i == 2 else "#eef3f9")
    for a, b in zip(xs, xs[1:]):
        arrow((a + 0.77, top), (b - 0.77, top))
    box(9.95, low, "Final answer\nLLM summary of the\nverified RESULT", fill="#e8f6ef", edge="#13795b")
    box(6.31, low, "Reflection (LLM)\ndiagnosis, lesson,\nnext plan", fill="#f3effb", edge="#5b3fa8")
    box(3.6, low, "Reflexion memory\n(all reflections\nso far)", fill="#f3effb", edge="#5b3fa8")
    arrow((9.95, top - 0.47), (9.95, low + 0.47), color="#13795b")
    note(10.3, 2.15, "pass", color="#13795b")
    arrow((6.31, top - 0.47), (6.31, low + 0.47), color="#b42318")
    note(5.85, 2.15, "blocked", color="#b42318")
    arrow((8.13, top - 0.47), (6.75, low + 0.47), color="#b42318")
    arrow((9.6, top - 0.47), (7.0, low + 0.42), color="#b42318")
    note(8.2, 1.0, "fail: Observation\n(kind + clean traceback)", color="#b42318")
    arrow((6.31 - 0.77, low), (3.6 + 0.77, low))
    arrow((3.4, low + 0.47), (2.67, top - 0.47))
    note(1.75, 2.0, "next attempt:\nprevious code + observation\n+ memory + loop-guard nudge")
    ax.text(5.4, 0.18, "The loop stops when a program passes its own self-checks or after "
            "max_attempts; every step is saved to runs/<id>.json", ha="center", fontsize=7.6,
            color=MUTED)
    return _save(fig, path)


def arm_bars(summary: dict, path: Path) -> Path:
    arms = [a for a in ARM_COLORS if a in summary]
    metrics = [("Accuracy vs reference (%)", lambda s: 100 * s["accuracy"], "{:.0f}%"),
               ("Average attempts per run", lambda s: s["avg_attempts"], "{:.2f}"),
               ("Average cost per run (US cents)",
                lambda s: 100 * s["cost_usd"] / max(s["runs"], 1), "{:.2f}")]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.3))
    for ax, (title, fn, fmt) in zip(axes, metrics):
        values = [fn(summary[a]) for a in arms]
        x = np.arange(len(arms))
        bars = ax.bar(x, values, width=0.62, color=[ARM_COLORS[a] for a in arms],
                      edgecolor="white", linewidth=2)
        for bar, v in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), fmt.format(v),
                    ha="center", va="bottom", fontsize=8, color=INK)
        ax.set_title(title, fontsize=9.5, color=NAVY, loc="left")
        ax.set_xticks(x, [ARM_LABELS[a] for a in arms], rotation=18, ha="right")
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_ylim(0, max(values) * 1.18 if max(values) > 0 else 1)
    fig.tight_layout()
    return _save(fig, path)


def _heatmap(ax, matrix, rows, cols, labels=None, vmax=None):
    ax.imshow(matrix, cmap=BLUES, aspect="auto", vmin=0, vmax=vmax or max(matrix.max(), 1))
    ax.set_xticks(range(len(cols)), cols, rotation=20, ha="right")
    ax.set_yticks(range(len(rows)), rows)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)
    top = vmax or max(matrix.max(), 1)
    for i in range(len(rows)):
        for j in range(len(cols)):
            text = labels[i][j] if labels else f"{matrix[i, j]:g}"
            ax.text(j, i, text, ha="center", va="center", fontsize=8.5,
                    color="white" if matrix[i, j] > 0.55 * top else INK)
    ax.set_xticks(np.arange(-0.5, len(cols)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(rows)), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", length=0)


def failure_kinds(summary: dict, path: Path) -> Path:
    arms = [a for a in ARM_COLORS if a in summary]
    kinds = [k for k in KINDS if any(summary[a]["failure_kinds"].get(k) for a in arms)] or KINDS
    matrix = np.array([[summary[a]["failure_kinds"].get(k, 0) for k in kinds] for a in arms], float)
    fig, ax = plt.subplots(figsize=(6.6, 2.6))
    _heatmap(ax, matrix, [ARM_LABELS[a] for a in arms], kinds)
    ax.set_title("Failed attempts by failure kind (count)", fontsize=9.5, color=NAVY, loc="left")
    return _save(fig, path)


def per_task(rows: list[dict], task_ids: list[str], path: Path) -> Path:
    arms = [a for a in ARM_COLORS if any(r["arm"] == a for r in rows)]
    matrix = np.full((len(task_ids), len(arms)), np.nan)
    labels = [["" for _ in arms] for _ in task_ids]
    for i, t in enumerate(task_ids):
        for j, a in enumerate(arms):
            group = [r for r in rows if r["task_id"] == t and r["arm"] == a]
            if group:
                matrix[i, j] = sum(r["correct"] for r in group) / len(group)
                labels[i][j] = f"{sum(r['correct'] for r in group)}/{len(group)}"
            else:
                labels[i][j] = "-"
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    _heatmap(ax, np.nan_to_num(matrix, nan=0.0), task_ids, [ARM_LABELS[a] for a in arms],
             labels=labels, vmax=1.0)
    ax.set_title("Correct runs per task and arm", fontsize=9.5, color=NAVY, loc="left")
    return _save(fig, path)
