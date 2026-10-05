// Results page: benchmark KPIs, charts, model comparison, task x arm heatmap, injected-bug
// attribution and the sandbox safety evaluation. Every number comes from results/*.json.

import { api } from "../api.js";
import { h, icon, clear } from "../dom.js";
import { barChart, groupedBarChart, responsiveChart } from "../charts.js";
import { fmtCost, fmtInt, fmtPct, fullDate, kindOf } from "../format.js";

const ARM_COLORS = { one_shot: "var(--k-blocked)", quantsolve: "var(--accent)",
  "quantsolve+inject": "var(--k-assertion)", "quantsolve+crash": "var(--teal)" };
const OUTCOMES = [
  { id: "caught", label: "Caught", color: "var(--k-ok)", text: "The bug made a check (or the interpreter) fail, so the loop could repair it." },
  { id: "silent", label: "Silent", color: "var(--k-runtime)", text: "The bug changed the answer, yet every self-check still passed." },
  { id: "benign", label: "Benign", color: "var(--k-blocked)", text: "The bug did not change the answer at all." },
  { id: "original_failed", label: "Original failed", color: "var(--k-assertion)", text: "The model's own program already failed, so the outcome cannot be pinned on the bug." },
  { id: "not_applied", label: "Not applied", color: "var(--text-3)", text: "The injector found no place to insert the bug." },
];

export async function mount(root, _params, ctx) {
  root.append(h("div", { class: "kpis" }, [0, 1, 2, 3].map(() => h("div", { class: "card kpi" },
    h("div", { class: "skeleton", style: { height: "38px", width: "38px" } }), h("div", { class: "skeleton", style: { height: "30px", width: "50%" } })))));
  const data = await api("/api/results");
  clear(root);
  const b = data.benchmark;
  root.append(h("div", { class: "page-head" }, h("div", {},
    h("span", { class: "eyebrow", text: "Evaluation" }), h("h1", { text: "Benchmark results" }),
    h("p", { text: "Eight multi-step problems with hand-written reference answers, each run twice per arm. One-shot generation is compared with the self-healing loop, with and without a bug deliberately injected into the first attempt." })),
    b ? h("div", { class: "meta-bar" }, h("span", { class: "chip" }, icon("spark"), b.meta.model),
      h("span", { class: "chip" }, icon("refresh"), `max ${b.meta.max_attempts} attempts`),
      h("span", { class: "chip" }, icon("clock"), fullDate(b.meta.created_at))) : null));
  if (!b) {
    root.append(h("div", { class: "card empty" }, h("div", { class: "icon-wrap" }, icon("chart", "icon xl")),
      h("h2", { text: "No benchmark yet" }), h("p", {}, "Run ", h("code", { text: "python3 cli.py bench" }), " to create results/benchmark.json.")));
    return;
  }
  const S = b.summary, L = data.arm_labels;
  const one = S.one_shot, loop = S.quantsolve, crash = S["quantsolve+crash"];
  const safety = data.safety;
  const gain = Math.round((loop.accuracy - one.accuracy) * 100);

  // ---------------------------------------------------------------- KPIs
  root.append(h("div", { class: "kpis" },
    kpi("target", "var(--accent)", fmtPct(loop.accuracy), "Loop accuracy",
      h("span", {}, h("span", { class: "delta" }, icon("trend", "icon sm"), `${gain >= 0 ? "+" : ""}${gain} pts`), ` vs one-shot (${fmtPct(one.accuracy)})`)),
    crash ? kpi("bug", "var(--teal)", `${crash.healed}/${crash.runs}`, "Injected crashes repaired",
      `${crash.correct} of ${crash.runs} final answers matched the reference`) : null,
    safety ? kpi("shield", "var(--k-ok)", `${safety.contained}/${safety.total}`, "Sandbox attacks contained",
      "escape, file, network and resource-exhaustion attempts") : null,
    kpi("coins", "var(--k-assertion)", fmtCost(loop.cost_usd / loop.runs), "Average cost of a loop run",
      `${fmtInt(Math.round(loop.tokens / loop.runs))} tokens · ${loop.avg_attempts.toFixed(2)} attempts on average`)));

  // ---------------------------------------------------------------- charts per arm
  const arms = b.arms;
  const maxAttempts = Math.ceil(Math.max(...arms.map((a) => S[a].avg_attempts)));
  const SHORT = { one_shot: "One-shot", quantsolve: "Loop", "quantsolve+inject": "Logic bug", "quantsolve+crash": "Crash bug" };
  const items = (fn, display) => arms.map((a) => ({ label: SHORT[a] || L[a] || a, value: fn(S[a]), color: ARM_COLORS[a], display: display ? display(S[a]) : undefined }));
  root.append(h("div", { class: "grid-3", style: { marginBottom: "var(--s5)" } },
    chartCard("Accuracy vs the reference", "share of runs whose RESULT matched the hand-written answer",
      responsiveChart((w) => barChart(items((s) => s.accuracy * 100, (s) => `${Math.round(s.accuracy * 100)}%`), { width: w, max: 100, format: (v) => `${Math.round(v)}%` }))),
    chartCard("Attempts per run", "average number of programs written before stopping",
      responsiveChart((w) => barChart(items((s) => s.avg_attempts, (s) => s.avg_attempts.toFixed(2)),
        { width: w, max: maxAttempts, ticks: maxAttempts, format: (v) => String(Math.round(v)) }))),
    chartCard("Cost per run", "US cents, estimated from token counts",
      responsiveChart((w) => barChart(items((s) => (s.cost_usd / s.runs) * 100, (s) => `${((s.cost_usd / s.runs) * 100).toFixed(2)}¢`), { width: w, format: (v) => `${v.toFixed(2)}¢` })))));

  // ---------------------------------------------------------------- model comparison
  if (data.comparison.length > 1) {
    const series = data.comparison.map((m, i) => ({ name: m.model, color: i === 0 ? "var(--k-blocked)" : "var(--accent)" }));
    const groups = arms.map((a) => ({ label: L[a] || a, values: data.comparison.map((m) => (m.arms[a] ? m.arms[a].accuracy * 100 : 0)) }));
    const [weak, strong] = data.comparison;
    const fixed = (m) => {
      const o = m.arms.one_shot, l = m.arms.quantsolve;
      return o && l && o.runs - o.correct > 0 ? Math.round(((l.correct - o.correct) / (o.runs - o.correct)) * 100) : 0;
    };
    root.append(h("section", { class: "card", style: { marginBottom: "var(--s5)" } },
      h("div", { class: "card-head" }, h("h2", {}, icon("layers"), "Does the loop help every model equally?"), h("span", { class: "spacer" }),
        h("div", { class: "legend" }, series.map((s) => h("span", {}, h("i", { style: { background: s.color } }), s.name)))),
      h("div", { class: "grid-2", style: { padding: "var(--s5)", alignItems: "center" } },
        responsiveChart((w) => groupedBarChart(groups, series, { width: w, max: 100, format: (v) => `${Math.round(v)}%` })),
        h("div", { class: "stack", style: { gap: "12px" } },
          h("p", { class: "note" }, "The same tasks, arms and prompts were run with both models. The loop turned ",
            h("b", { text: `${fixed(weak)}%` }), ` of ${weak.model}'s one-shot errors into correct answers, and `,
            h("b", { text: `${fixed(strong)}%` }), ` of ${strong.model}'s.`),
          h("p", { class: "note", text: "Self-correction does not add knowledge: it turns a failed check into another try, which only helps if the model can read the observation, find the real cause and write a correct fix. The stronger model does that more often." }),
          h("p", { class: "hint", text: "Each bar rests on 6–16 runs, so treat small differences as noise." })))));
  }

  // ---------------------------------------------------------------- heatmap
  const detail = h("div", { class: "cell-detail", hidden: true });
  const table = h("table", { class: "heat" });
  table.append(h("thead", {}, h("tr", {}, h("th", { text: "Task" }), arms.map((a) => h("th", { text: L[a] || a })))));
  const body = h("tbody");
  let pressed = null;
  for (const t of b.tasks) {
    const tr = h("tr", {}, h("th", { text: t.title }));
    for (const a of arms) {
      const cell = b.matrix[t.id][a];
      if (!cell.runs) { tr.append(h("td", {}, h("div", { class: "na", text: "—", title: "not run for this task" }))); continue; }
      const ratio = cell.correct / cell.runs;
      const c = ratio >= 0.999 ? "var(--k-ok)" : ratio <= 0.001 ? "var(--k-runtime)" : "var(--k-assertion)";
      const btn = h("button", { type: "button", "aria-pressed": "false", title: `${t.title} · ${L[a]}: ${cell.correct} of ${cell.runs} correct`,
        style: { background: `color-mix(in srgb, ${c} 20%, var(--surface))`, borderColor: `color-mix(in srgb, ${c} 45%, transparent)` } },
        `${cell.correct}/${cell.runs}`);
      btn.addEventListener("click", () => {
        if (pressed) pressed.setAttribute("aria-pressed", "false");
        pressed = btn; btn.setAttribute("aria-pressed", "true");
        detail.hidden = false;
        detail.replaceChildren(h("b", { text: `${t.title} · ${L[a]}` }),
          h("div", { class: "runs" }, cell.items.map((it, i) => h("a", { class: `chip ${it.correct ? "ok" : "bad"}`, href: `#/run/${it.id}` },
            icon(it.correct ? "check" : "x"), `Run ${i + 1} · ${it.attempts} attempt${it.attempts === 1 ? "" : "s"}`, icon("chevron-right")))),
          h("span", { class: "hint", text: "Open a run to replay every attempt." }));
      });
      tr.append(h("td", {}, btn));
    }
    body.append(tr);
  }
  table.append(body);
  root.append(h("section", { class: "card", style: { marginBottom: "var(--s5)" } },
    h("div", { class: "card-head" }, h("h2", {}, icon("hash"), "Correct runs per task and arm"), h("span", { class: "spacer" }),
      h("span", { class: "hint", text: "click a cell to open its runs" })),
    h("div", { style: { padding: "var(--s4) var(--s5) var(--s5)", overflowX: "auto" } }, table, detail)));

  // ---------------------------------------------------------------- injected bugs
  const injectArms = arms.filter((a) => Object.keys(S[a].inject_outcomes || {}).length);
  if (injectArms.length) {
    const blocks = injectArms.map((a) => {
      const o = S[a].inject_outcomes, total = Object.values(o).reduce((x, y) => x + y, 0);
      return h("div", { class: "stack", style: { gap: "8px" } },
        h("div", { style: { display: "flex", justifyContent: "space-between", fontSize: ".88rem" } }, h("b", { text: L[a] }), h("span", { class: "hint", text: `${total} runs` })),
        h("div", { class: "stackbar" }, OUTCOMES.filter((x) => o[x.id]).map((x) =>
          h("span", { style: { width: `${(o[x.id] / total) * 100}%`, background: x.color }, title: `${x.label}: ${o[x.id]}` }, String(o[x.id])))));
    });
    root.append(h("section", { class: "card", style: { marginBottom: "var(--s5)" } },
      h("div", { class: "card-head" }, h("h2", {}, icon("bug"), "Did the self-checks catch the injected bugs?")),
      h("div", { class: "grid-2", style: { padding: "var(--s5)" } },
        h("div", { class: "stack", style: { gap: "var(--s4)" } }, blocks,
          h("p", { class: "note", text: "Each injected run was re-run offline with the model's original, un-mutated program, so a failure can be attributed to the bug or to the model's own code." })),
        h("div", { class: "stack", style: { gap: "10px" } }, OUTCOMES.map((x) => h("div", { style: { display: "flex", gap: "10px", alignItems: "flex-start", fontSize: ".87rem" } },
          h("i", { style: { width: "12px", height: "12px", borderRadius: "4px", background: x.color, flex: "none", marginTop: "4px" } }),
          h("span", {}, h("b", { text: `${x.label}: ` }), h("span", { class: "muted", text: x.text }))))))));
  }

  // ---------------------------------------------------------------- safety
  if (safety) {
    const rows = safety.attacks.map((a) => h("tr", {},
      h("td", {}, h("span", { class: `chip ${a.contained ? "ok" : "bad"}` }, icon(a.contained ? "check" : "x"), a.contained ? "Contained" : "Escaped")),
      h("td", {}, h("details", { class: "safety-row" }, h("summary", {}, h("b", { text: a.title }), icon("chevron", "icon sm")),
        h("pre", { class: "trace", style: { marginTop: "8px" }, text: a.code }))),
      h("td", {}, h("span", { class: "chip" }, icon(a.gate ? "shield" : "lock"), a.gate ? "gate on" : "gate off")),
      h("td", {}, h("span", { class: `chip kind k-${a.kind}` }, icon(kindOf(a.kind).icon), a.kind)),
      h("td", { class: "muted", text: a.detail || a.message })));
    root.append(h("section", { class: "card", style: { marginBottom: "var(--s5)" } },
      h("div", { class: "card-head" }, h("h2", {}, icon("shield"), "Sandbox safety evaluation"), h("span", { class: "spacer" }),
        h("span", { class: "chip ok" }, icon("check"), `${safety.contained}/${safety.total} contained`)),
      h("div", { style: { overflowX: "auto" } }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, ["Result", "Attack (click for code)", "AST gate", "Outcome", "Detail"].map((t) => h("th", { text: t })))),
        h("tbody", {}, rows))),
      h("p", { class: "note", style: { padding: "var(--s4) var(--s5)" }, text: "Rows with the gate off show that the runtime layers (restricted builtins, guarded import, separate process with a scrubbed environment, CPU and memory limits, timeout) still hold on their own." })));
  }

  root.append(h("section", { class: "card card-pad" }, h("h3", { style: { marginBottom: "8px" } }, "Method"),
    h("p", { class: "note" }, `${b.tasks.length} tasks × ${b.meta.repeats} repeats per arm with ${b.meta.model}, at most ${b.meta.max_attempts} attempts and a ${b.meta.timeout_s} s sandbox timeout. `,
      "One-shot allows a single attempt. Loop is the full ReAct + Reflexion loop. The bug arms inject a fault into attempt 1 only (crash: a misspelled variable on ",
      `${(b.meta.crash_tasks || []).length} tasks; logic: an off-by-one or a flipped sign). A run is correct only if every RESULT value is within tolerance of the hand-written reference.`)));
  void ctx;
}

function kpi(iconName, color, value, label, sub) {
  return h("section", { class: "card kpi" },
    h("div", { class: "kpi-icon", style: { background: `color-mix(in srgb, ${color} 14%, transparent)`, color } }, icon(iconName)),
    h("div", { class: "kv1", text: value }), h("div", { class: "kl", text: label }), h("div", { class: "ks" }, sub));
}

function chartCard(title, sub, chart) {
  return h("section", { class: "card" }, h("div", { class: "card-head", style: { flexDirection: "column", alignItems: "flex-start", gap: "2px" } },
    h("h3", { text: title }), h("span", { class: "hint", text: sub })), h("div", { style: { padding: "var(--s4) var(--s4) var(--s3)" } }, chart));
}
