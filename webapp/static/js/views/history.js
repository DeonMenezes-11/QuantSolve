// History page: every saved run, searchable and filterable, with attempt dots showing the
// path each run took (red/amber/... for failures, green for the passing attempt).

import { api } from "../api.js";
import { h, icon, clear, segmented } from "../dom.js";
import { fmtDuration, fmtCost, relTime, fullDate, kindOf, INJECT_LABELS } from "../format.js";

const SCOPES = [
  { value: "mine", label: "Your runs" },
  { value: "bench", label: "Benchmark" },
  { value: "archive", label: "Archive" },
  { value: "all", label: "All" },
];
const SOURCE_LABEL = { mine: "your run", bench: "benchmark", archive: "archive" };
const FILTER_KEY = "qs-history";

export async function mount(root, _params, ctx) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  let saved = {};
  try { saved = JSON.parse(sessionStorage.getItem(FILTER_KEY) || "{}"); } catch { /* ignore */ }
  const state = {
    scope: params.get("scope") || saved.scope || "mine",
    status: saved.status || "all",
    bug: saved.bug || "any",
    sort: saved.sort || "new",
    q: params.get("q") || "",
  };
  let rows = [];
  const persist = () => { try { sessionStorage.setItem(FILTER_KEY, JSON.stringify({ ...state, q: undefined })); } catch { /* ignore */ } };

  const search = h("input", { class: "input", type: "search", placeholder: "Search runs by problem…", value: state.q, "aria-label": "Search runs" });
  const list = h("div", { class: "run-list", "aria-live": "polite" });
  const foot = h("div", { class: "list-foot" });

  const scopeSeg = segmented(SCOPES, state.scope, (v) => setScope(v), { compact: true, label: "Source" });
  const setScope = (v) => { state.scope = v; scopeSeg.setValue(v); persist(); load(); };
  const toolbar = h("div", { class: "toolbar" },
    h("div", { class: "input-icon search" }, icon("search"), search),
    h("div", { class: "filter-group" }, h("span", { class: "fl", text: "Source" }), scopeSeg),
    h("div", { class: "filter-group" }, h("span", { class: "fl", text: "Status" }),
      segmented([{ value: "all", label: "All" }, { value: "ok", label: "Verified" }, { value: "bad", label: "Not verified" }],
        state.status, (v) => { state.status = v; persist(); render(); }, { compact: true, label: "Status" })),
    h("div", { class: "filter-group" }, h("span", { class: "fl", text: "Demo bug" }),
      segmented([{ value: "any", label: "Any" }, { value: "none", label: "None" }, { value: "crash", label: "Crash" }, { value: "logic", label: "Logic" }],
        state.bug, (v) => { state.bug = v; persist(); render(); }, { compact: true, label: "Demo bug" })),
    h("div", { class: "filter-group" }, h("span", { class: "fl", text: "Sort" }),
      segmented([{ value: "new", label: "Newest" }, { value: "attempts", label: "Most attempts" }],
        state.sort, (v) => { state.sort = v; persist(); render(); }, { compact: true, label: "Sort" })));

  root.append(
    h("div", { class: "page-head" }, h("div", {},
      h("span", { class: "eyebrow", text: "Saved runs" }), h("h1", { text: "History" }),
      h("p", { text: "Every run is saved with its full trace. Open one to replay each attempt: the code, what the sandbox saw and the lesson the model wrote down." }))),
    h("section", { class: "card" }, toolbar,
      h("div", { class: "run-list-head", "aria-hidden": "true" },
        h("span"), h("span", { text: "Problem" }), h("span", { class: "hide-sm", text: "Attempts" }),
        h("span", { class: "num hide-md hide-sm", text: "Time" }), h("span", { class: "num hide-md hide-sm", text: "Cost" }),
        h("span", { class: "num hide-sm", text: "When" }), h("span")),
      list, foot));

  let timer = null;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { state.q = search.value; render(); }, 120); });

  function skeleton() {
    clear(list);
    for (let i = 0; i < 6; i++) {
      list.append(h("div", { class: "run-row" }, h("div", { class: "skeleton", style: { width: "34px", height: "34px" } }),
        h("div", {}, h("div", { class: "skeleton", style: { height: "14px", width: `${50 + (i * 7) % 40}%` } }),
          h("div", { class: "skeleton", style: { height: "10px", width: "30%", marginTop: "8px" } }))));
    }
    foot.textContent = "Loading…";
  }

  async function load() {
    skeleton();
    try {
      rows = await api(`/api/history?scope=${state.scope}`);
    } catch (err) {
      rows = [];
      ctx.toast(err.message, "bad");
    }
    render();
  }

  function render() {
    const q = state.q.trim().toLowerCase();
    let shown = rows.filter((r) =>
      (state.status === "all" || (state.status === "ok" ? r.success : !r.success)) &&
      (state.bug === "any" || (state.bug === "none" ? !r.inject : r.inject === state.bug)) &&
      (!q || `${r.title} ${r.task_id || ""} ${r.id}`.toLowerCase().includes(q)));
    if (state.sort === "attempts") shown = [...shown].sort((a, b) => b.kinds.length - a.kinds.length);
    clear(list);
    if (!shown.length) {
      const nothingSaved = rows.length === 0 && state.scope === "mine";
      list.append(h("div", { class: "empty" }, h("div", { class: "icon-wrap" }, icon(nothingSaved ? "history" : "search", "icon xl")),
        h("h3", { text: nothingSaved ? "No runs of your own yet" : "No runs match these filters" }),
        h("p", { text: nothingSaved ? "Solve a problem and it will appear here. Meanwhile, browse the benchmark runs." : "Try another search or clear a filter." }),
        nothingSaved ? h("div", { style: { display: "flex", gap: "8px" } },
          h("a", { class: "btn primary", href: "#/solve" }, icon("zap", "icon sm"), "Solve a problem"),
          h("button", { class: "btn", type: "button", onclick: () => setScope("bench") }, "Show benchmark runs")) : null));
    } else {
      for (const r of shown) list.append(row(r));
    }
    foot.replaceChildren(h("span", { text: `Showing ${shown.length} of ${rows.length} run${rows.length === 1 ? "" : "s"}` }),
      h("span", { class: "dots" }, legendDot("ok"), " passed ", legendDot("runtime"), " crashed ", legendDot("assertion"), " self-check failed ", legendDot("blocked"), " blocked"));
  }

  load();
  return () => clearTimeout(timer);
}

function legendDot(kind) { return h("i", { class: kind === "ok" ? "ok" : "", style: kind === "ok" ? {} : { "--c": `var(--k-${kind})` } }); }

function row(r) {
  const state = r.success ? "ok" : r.stopped ? "stopped" : "bad";
  const dots = h("span", { class: "dots", title: r.kinds.map((k, i) => `#${i + 1} ${kindOf(k).label}`).join(" → ") },
    r.kinds.map((k) => h("i", { class: k === "ok" ? "ok" : "", style: k === "ok" ? {} : { "--c": `var(--k-${k})` } })));
  const sub = [
    h("span", { text: r.model }),
    r.inject ? h("span", { class: "chip warn", style: { height: "20px", fontSize: ".7rem" } }, icon("bug"), INJECT_LABELS[r.inject] || r.inject) : null,
    r.correct === true ? h("span", { class: "chip ok", style: { height: "20px", fontSize: ".7rem" } }, icon("target"), "matches reference") : null,
    r.correct === false && r.success ? h("span", { class: "chip bad", style: { height: "20px", fontSize: ".7rem" } }, icon("x"), "differs from reference") : null,
    r.source !== "mine" ? h("span", { text: `· ${SOURCE_LABEL[r.source]}` }) : null,
  ];
  return h("a", { class: "run-row", href: `#/run/${encodeURIComponent(r.id)}`, title: `${r.title}\n${fullDate(r.created_at)}` },
    h("span", { class: `rr-status ${state}` }, icon(state === "ok" ? "check" : state === "stopped" ? "stop" : "x")),
    h("span", { class: "rr-title" }, h("b", { text: r.title }), h("small", {}, sub)),
    h("span", { class: "hide-sm" }, dots),
    h("span", { class: "num hide-md hide-sm", text: fmtDuration(r.duration_s) }),
    h("span", { class: "num hide-md hide-sm", text: fmtCost(r.cost_usd) }),
    h("span", { class: "num hide-sm", text: relTime(r.created_at) }),
    icon("chevron-right", "icon chev"));
}
