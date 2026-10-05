// Run replay page (#/run/<id>): the saved trace rendered with the same components as a live run.

import { api } from "../api.js";
import { h, icon, copyText } from "../dom.js";
import { RunView, memoryList } from "../runview.js";
import { fmtDuration, fmtCost, fmtInt, fullDate, INJECT_LABELS } from "../format.js";

const SOURCE_LABEL = { mine: "Your run", bench: "Benchmark run", archive: "Archived run" };

export async function mount(root, [runId], ctx) {
  root.append(h("div", { class: "card card-pad" }, h("div", { class: "skeleton", style: { height: "26px", width: "40%" } }),
    h("div", { class: "skeleton", style: { height: "14px", width: "70%", marginTop: "14px" } }),
    h("div", { class: "skeleton", style: { height: "220px", marginTop: "22px" } })));
  let data;
  try {
    data = await api(`/api/history/${encodeURIComponent(decodeURIComponent(runId))}`);
  } catch (err) {
    root.replaceChildren(h("div", { class: "card empty" }, h("div", { class: "icon-wrap" }, icon("search", "icon xl")),
      h("h2", { text: "Run not found" }), h("p", { text: err.message }),
      h("a", { class: "btn", href: "#/history" }, icon("arrow-left", "icon sm"), "Back to History")));
    return;
  }
  const { trace, score, source, task_title: taskTitle } = data;
  const title = taskTitle || (trace.task || "").split("\n")[0].slice(0, 120);
  document.title = `${title} · QuantSolve`;
  const state = trace.success ? "ok" : trace.stopped ? "stopped" : "bad";
  const link = `${location.origin}${location.pathname}#/run/${trace.run_id}`;

  const statusChip = h("span", { class: `chip ${state === "ok" ? "ok" : state === "bad" ? "bad" : ""}` },
    icon(state === "ok" ? "check" : state === "stopped" ? "stop" : "x"),
    state === "ok" ? `Verified in ${trace.attempts.length} attempt${trace.attempts.length === 1 ? "" : "s"}` : state === "stopped" ? "Stopped" : "Not verified");
  const metaBar = h("div", { class: "meta-bar" }, statusChip,
    score && trace.success ? h("span", { class: `chip ${score.correct ? "ok" : "bad"}` }, icon(score.correct ? "target" : "x"), score.correct ? "Matches reference" : "Differs from reference") : null,
    h("span", { class: "chip" }, icon("spark"), trace.model),
    trace.inject ? h("span", { class: "chip warn" }, icon("bug"), `${INJECT_LABELS[trace.inject]} injected`) : null,
    h("span", { class: "chip" }, icon("history"), SOURCE_LABEL[source] || source),
    h("span", { class: "chip" }, icon("clock"), fullDate(trace.created_at)));

  const problem = h("section", { class: "card problem-card clamped" },
    h("div", { class: "section-title" }, h("span", { class: "label", text: "Problem" }), h("span", { class: "hint", text: trace.task_id ? `sample: ${trace.task_id}` : "free text" })),
    h("p", { class: "pt", text: trace.task }));
  const toggle = h("button", { class: "btn sm ghost", type: "button", style: { marginTop: "8px" } }, icon("chevron", "icon sm"), "Show the full problem");
  toggle.addEventListener("click", () => {
    const clamped = problem.classList.toggle("clamped");
    toggle.replaceChildren(icon("chevron", "icon sm"), clamped ? "Show the full problem" : "Show less");
  });
  if (trace.task.length > 320) problem.append(toggle); else problem.classList.remove("clamped");

  const timeline = h("div", { class: "run-panel" });
  const u = trace.usage || {};
  const reflections = trace.attempts.filter((a) => a.reflection).map((a) => a.reflection);
  const side = h("aside", { class: "side-sticky" },
    h("section", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, icon("info"), "Run facts")),
      h("div", { class: "card-pad", style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" } },
        fact(String(trace.attempts.length), "Attempts"), fact(fmtDuration(trace.duration_s), "Time"),
        fact(fmtInt(u.total_tokens), "Tokens"), fact(fmtCost(u.cost_usd), "Cost"),
        fact(String(u.calls ?? "—"), "LLM calls"), fact(String(trace.max_attempts), "Attempt budget"))),
    h("section", { class: "card card-pad", style: { display: "flex", flexDirection: "column", gap: "8px" } },
      h("button", { class: "btn block", type: "button", onclick: async () => { await copyText(link); ctx.toast("Link copied", "ok", 1500); } }, icon("link", "icon sm"), "Copy share link"),
      h("button", { class: "btn block", type: "button", onclick: () => {
        try { sessionStorage.removeItem("qs-last"); sessionStorage.setItem("qs-prefill", JSON.stringify(trace.task)); } catch { /* ignore */ }
        ctx.go("#/solve");
      } }, icon("refresh", "icon sm"), "Solve this problem again"),
      h("a", { class: "btn ghost block", href: "#/history" }, icon("arrow-left", "icon sm"), "Back to History")),
    h("section", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, icon("brain"), "Reflexion memory")),
      h("div", { class: "memory" }, memoryList(reflections))));

  root.replaceChildren(
    h("div", { class: "crumbs" }, h("a", { href: "#/history", text: "History" }), icon("chevron-right", "icon sm"), h("span", { text: trace.run_id })),
    h("div", { class: "page-head" }, h("div", { style: { minWidth: 0 } }, h("h1", { text: title }), metaBar)),
    h("div", { class: "replay-grid" }, h("div", { class: "stack" }, problem, timeline), side));
  RunView.replay(timeline, trace, score);
}

function fact(v, k) { return h("div", { class: "stat" }, h("span", { class: "v", text: v }), h("span", { class: "k", text: k })); }
