// Renders a run: the live pipeline stepper, the attempt timeline, Reflexion memory and the final
// answer. The same renderer is used for live runs (fed by SSE events) and saved-run replays.

import { h, icon, clear, copyText, tabBar, append } from "./dom.js";
import { highlightLines } from "./highlight.js";
import { diffLines, withContext, changeCount } from "./diff.js";
import { fmtValue, fmtDuration, fmtCost, fmtInt, kindOf, errorHeadline, INJECT_LABELS } from "./format.js";

const PIPE_STEPS = [
  { id: "llm", label: "Plan & code", icon: "spark" },
  { id: "gate", label: "Safety gate", icon: "shield" },
  { id: "run", label: "Run", icon: "cpu" },
  { id: "check", label: "Self-checks", icon: "check" },
  { id: "reflect", label: "Reflect", icon: "brain" },
];

/** Where in the pipeline did an observation fail? */
function failedStage(kind) {
  if (kind === "blocked" || kind === "syntax") return "gate";
  if (kind === "runtime" || kind === "timeout") return "run";
  return "check";
}

/** Stepper states after a failed observation: stages before the failure green, it red. */
function failStates(kind, reflect) {
  const states = { llm: "done", reflect };
  for (const s of ["gate", "run", "check"]) {
    if (s === failedStage(kind)) { states[s] = "fail"; break; }
    states[s] = "done";
  }
  return states;
}

function faultLine(injected) {
  const m = /line (\d+)/.exec(injected || "");
  return m ? Number(m[1]) : null;
}

// ------------------------------------------------------------------ code rendering

export function codeBlock(code, { errorLine = null, faultAt = null } = {}) {
  const lines = highlightLines(code || "");
  const table = h("table");
  const body = h("tbody");
  lines.forEach((html, i) => {
    const n = i + 1;
    const cls = n === errorLine ? "err" : n === faultAt ? "fault" : null;
    const lc = h("td", { class: "lc" });
    lc.innerHTML = html || " "; // html is produced by highlight.js from escaped text
    body.append(h("tr", { class: cls }, h("td", { class: "ln", text: String(n) }), lc));
  });
  table.append(body);
  return h("div", { class: "code" }, table);
}

function diffBlock(before, after) {
  const ops = withContext(diffLines(before, after));
  const body = h("tbody");
  for (const op of ops) {
    if (op.t === "gap") {
      body.append(h("tr", {}, h("td", { class: "ln", text: "⋯" }), h("td", { class: "sign" }),
        h("td", { class: "lc", style: { color: "var(--code-gutter)" }, text: `${op.count} unchanged line${op.count === 1 ? "" : "s"}` })));
      continue;
    }
    const lc = h("td", { class: "lc" });
    lc.innerHTML = highlightLines(op.text)[0] || " ";
    body.append(h("tr", { class: op.t === "+" ? "add" : op.t === "-" ? "del" : null },
      h("td", { class: "ln", text: String(op.t === "-" ? op.ai : op.bi) }),
      h("td", { class: "sign", text: op.t === "=" ? " " : op.t }), lc));
  }
  return h("div", { class: "code" }, h("table", {}, body));
}

function traceBlock(text) {
  const pre = h("pre", { class: "trace" });
  for (const line of (text || "").split("\n")) {
    let cls = null;
    if (/^\s*line \d+, in /.test(line) || /^\s*File /.test(line)) cls = "tr-loc";
    else if (/^\w*(Error|Exception)\b|^AssertionError|^MemoryError|^Execution exceeded/.test(line.trim())) cls = "tr-err";
    else if (/^\s{4,}\S/.test(line)) cls = "tr-src";
    pre.append(cls ? h("span", { class: cls, text: line }) : line, "\n");
  }
  return pre;
}

export function resultTable(result) {
  const body = h("tbody");
  for (const [k, v] of Object.entries(result || {})) body.append(h("tr", {}, h("th", { text: k }), h("td", { text: fmtValue(v) })));
  return h("table", { class: "kv" }, body);
}

// ------------------------------------------------------------------ attempt card

class AttemptCard {
  constructor(number, { live, prevCode, onToggle }) {
    this.number = number;
    this.live = live;
    this.prevCode = prevCode;
    this.userToggled = false;
    this.data = { thought: "", code: "", llm_code: null, injected: null, observation: null, reflection: null, nudge: null };
    this.num = h("div", { class: "attempt-num", text: String(number) });
    this.line1 = h("div", { class: "line1" }, h("span", { text: `Attempt ${number}` }));
    this.chipSlot = h("span");
    this.line1.append(this.chipSlot);
    this.line2 = h("div", { class: "line2", text: "Planning and writing the program…" });
    this.metaEl = h("div", { class: "attempt-meta" });
    this.head = h("button", { class: "attempt-head", type: "button", "aria-expanded": "false" },
      this.num, h("div", { class: "attempt-summary" }, this.line1, this.line2), this.metaEl, icon("chevron", "icon chev"));
    this.head.addEventListener("click", () => { this.userToggled = true; this.setOpen(!this.open); onToggle?.(); });
    this.panes = {};
    this.paneWrap = h("div");
    this.tabs = tabBar([
      { id: "thought", label: "Thought", icon: "bulb" },
      { id: "code", label: "Code", icon: "code" },
      { id: "observation", label: "Observation", icon: "terminal" },
      { id: "reflection", label: "Reflection", icon: "brain" },
    ], (id) => this.showPane(id));
    this.body = h("div", { class: "attempt-body", hidden: true }, this.tabs.el, this.paneWrap);
    this.el = h("article", { class: "attempt is-running" }, this.head, this.body);
    this.tabs.setVisible("reflection", false);
    this.setRunning("Planning and writing the program…");
    this.current = "thought";
  }

  get open() { return !this.body.hidden; }

  setOpen(open) {
    this.body.hidden = !open;
    this.el.classList.toggle("open", open);
    this.head.setAttribute("aria-expanded", String(open));
    if (open) this.tabs.select(this.current);
  }

  setRunning(text) {
    clear(this.chipSlot).append(h("span", { class: "chip accent" }, h("span", { class: "spinner sm" }), "Working"));
    this.line2.textContent = text;
  }

  select(id) { this.current = id; this.tabs.select(id); }

  showPane(id) {
    this.current = id;
    clear(this.paneWrap).append(this.renderPane(id));
  }

  renderPane(id) {
    const d = this.data;
    const pane = h("div", { class: "attempt-pane" });
    if (id === "thought") {
      pane.append(h("p", { class: "thought", text: d.thought || "Waiting for the model…" }));
      if (d.injected) pane.append(this.faultBanner());
    } else if (id === "code") {
      if (!d.code) { pane.append(h("p", { class: "muted", text: "The program appears here once the model has written it." })); return pane; }
      let mode = "code";
      const view = h("div");
      const draw = () => {
        clear(view);
        if (mode === "diff" && this.prevCode) view.append(diffBlock(this.prevCode, d.code));
        else if (mode === "original" && d.llm_code) view.append(codeBlock(d.llm_code));
        else view.append(codeBlock(d.code, { errorLine: d.observation && !d.observation.ok ? d.observation.line : null, faultAt: faultLine(d.injected) }));
      };
      const opts = [{ value: "code", label: d.llm_code ? "Executed" : "Program" }];
      if (d.llm_code) opts.push({ value: "original", label: "Model's original" });
      if (this.prevCode) {
        const n = changeCount(diffLines(this.prevCode, d.code));
        opts.push({ value: "diff", label: `Changes vs attempt ${this.number - 1} (${n})` });
      }
      const toolbar = h("div", { class: "pane-toolbar" });
      if (opts.length > 1) {
        const seg = h("div", { class: "segmented compact" });
        const buttons = opts.map((o) => {
          const b = h("button", { type: "button", "aria-pressed": String(o.value === mode), text: o.label });
          b.addEventListener("click", () => { mode = o.value; buttons.forEach((x) => x.setAttribute("aria-pressed", String(x === b))); draw(); });
          return b;
        });
        buttons.forEach((b) => seg.append(b));
        toolbar.append(seg);
      }
      toolbar.append(h("span", { class: "spacer" }),
        h("button", { class: "btn sm ghost", type: "button", onclick: async (e) => {
          await copyText(mode === "original" ? d.llm_code : d.code);
          flash(e.currentTarget, "Copied");
        } }, icon("copy", "icon sm"), "Copy"));
      if (d.injected) pane.append(this.faultBanner());
      pane.append(toolbar, view);
      draw();
    } else if (id === "observation") {
      const obs = d.observation;
      if (!obs) { pane.append(h("p", { class: "muted" }, h("span", { class: "spinner sm" }), " Running in the sandbox…")); return pane; }
      const k = kindOf(obs.ok ? "ok" : obs.kind);
      pane.append(h("div", { class: `obs-banner k-${obs.ok ? "ok" : obs.kind}` },
        h("div", { class: "obs-icon" }, icon(k.icon)),
        h("div", {}, h("h4", { text: obs.ok ? `${obs.asserts} self-checks passed in ${fmtDuration(obs.duration_s)}` : k.label }),
          h("p", { text: obs.ok ? "RESULT returned by the program:" : k.explain }))));
      if (obs.ok) pane.append(resultTable(obs.result));
      else if (obs.traceback) pane.append(traceBlock(obs.traceback));
      else pane.append(traceBlock(obs.message));
      if (obs.stdout) {
        pane.append(h("details", { class: "more" }, h("summary", {}, icon("terminal", "icon sm"), "Printed output (stdout)"),
          h("pre", { class: "trace", text: obs.stdout.slice(0, 4000) })));
      }
    } else if (id === "reflection") {
      const r = d.reflection;
      if (!r) {
        pane.append(h("p", { class: "muted", text: d.observation && !d.observation.ok
          ? "No reflection: this was the last attempt." : "No reflection needed: this attempt passed." }));
      } else {
        pane.append(h("div", { class: "reflection" },
          reflItem("ri-diag", "search", "Diagnosis", r.diagnosis),
          reflItem("ri-lesson", "bulb", "Lesson stored in memory", r.reflection),
          reflItem("ri-plan", "arrow-right", "Plan for the next attempt", r.next_plan)));
      }
      if (d.nudge) pane.append(h("div", { class: "callout warn" }, icon("refresh"), h("div", {}, h("b", { text: "Loop guard: " }), d.nudge)));
    }
    return pane;
  }

  faultBanner() {
    return h("div", { class: "fault-banner" }, icon("bug"),
      h("div", {}, h("b", { text: "Demo fault injected: " }), this.data.injected,
        h("div", { class: "hint", style: { marginTop: "2px" }, text: "The model wrote correct code here; QuantSolve changed it on purpose to show the loop repairing it." })));
  }

  setAction({ thought, code, llm_code, injected }) {
    Object.assign(this.data, { thought, code, llm_code, injected });
    this.tabs.setBadge("code", code ? `${code.trimEnd().split("\n").length} lines` : null);
    if (this.live) this.setRunning(injected ? "Running in the sandbox (with an injected demo bug)…" : "Running in the sandbox…");
    if (this.open) this.showPane(this.current);
  }

  setObservation(obs) {
    this.data.observation = obs;
    const kind = obs.ok ? "ok" : obs.kind;
    const k = kindOf(kind);
    this.el.classList.remove("is-running");
    this.el.classList.add(obs.ok ? "is-ok" : "is-fail");
    if (!obs.ok) this.el.style.setProperty("--kc", `var(--k-${obs.kind})`);
    clear(this.chipSlot).append(h("span", { class: `chip kind k-${kind}` }, icon(k.icon), k.label));
    this.line2.textContent = errorHeadline(obs);
    this.line2.title = this.line2.textContent;
    clear(this.metaEl).append(h("span", { class: "dur" }, icon("clock", "icon sm"), " ", fmtDuration(obs.duration_s)));
    if (!obs.ok) this.tabs.setVisible("reflection", true);
    this.select("observation");
  }

  setReflection(reflection, nudge) {
    this.data.reflection = reflection;
    this.data.nudge = nudge;
    this.tabs.setVisible("reflection", true);
    if (this.live && !this.userToggled) this.select("reflection");
    else if (this.open && this.current === "reflection") this.showPane("reflection");
  }

  load(attempt) {
    this.setAction(attempt);
    this.setObservation(attempt.observation);
    if (attempt.reflection || attempt.nudge) this.setReflection(attempt.reflection, attempt.nudge);
    this.select("observation");
  }
}

function reflItem(cls, iconName, title, text) {
  return h("div", { class: `refl-item ${cls}` }, h("div", { class: "ri-icon" }, icon(iconName, "icon sm")),
    h("div", {}, h("h5", { text: title }), h("p", { text: text || "—" })));
}

function flash(button, text) {
  const old = [...button.childNodes];
  button.replaceChildren(icon("check", "icon sm"), text);
  setTimeout(() => button.replaceChildren(...old), 1400);
}

// ------------------------------------------------------------------ final card + memory

export function memoryList(reflections) {
  if (!reflections.length) return h("p", { class: "hint", text: "Empty: no attempt has failed, so there is nothing to learn from yet." });
  return h("ol", {}, reflections.map((r) => h("li", {}, h("span", { class: "chip warn", text: `after #${r.attempt}` }), h("span", { text: r.reflection }))));
}

export function finalCard(trace, score, { onRunAgain, live = false } = {}) {
  const ok = trace.success, stopped = trace.stopped;
  const state = ok ? "ok" : stopped ? "stopped" : "bad";
  const last = trace.attempts[trace.attempts.length - 1];
  const checks = score && score.checks ? score.checks : null;
  const title = ok ? "Verified answer" : stopped ? "Run stopped" : "No verified answer";
  const chips = [];
  if (ok && last) chips.push(h("span", { class: "chip ok" }, icon("check"), `${last.observation.asserts} self-checks passed`));
  if (checks && ok) {
    const good = Object.values(checks).filter((c) => c.ok).length, total = Object.keys(checks).length;
    chips.push(h("span", { class: `chip ${score.correct ? "ok" : "bad"}` }, icon(score.correct ? "target" : "x"),
      score.correct ? "Matches the reference" : `${good}/${total} match the reference`));
  }
  const banner = h("div", { class: "final-banner" },
    h("div", { class: "final-icon" }, icon(ok ? "check" : stopped ? "stop" : "x", "icon lg")),
    h("div", { class: "ft" }, h("h2", {}, title, ...chips), h("p", { class: "final-answer", text: trace.final_answer || "" })));
  const card = h("section", { class: `card final ${state}`, "aria-live": "polite" }, banner);

  if (trace.result && Object.keys(trace.result).length) {
    const tiles = h("div", { class: "result-tiles" });
    for (const [key, value] of Object.entries(trace.result)) {
      const c = checks ? checks[key] : null;
      tiles.append(h("div", { class: `tile${c ? (c.ok ? " right" : " wrong") : ""}` },
        h("div", { class: "tk", text: key, title: key }), h("div", { class: "tv", text: fmtValue(value) }),
        c ? h("div", { class: "tref" }, icon(c.ok ? "check" : "x", "icon sm"), c.ok ? "matches reference" : `reference: ${fmtValue(c.expected)}`) : null));
    }
    card.append(tiles);
  } else if (checks) {
    card.append(h("div", { class: "score-line" }, icon("info", "icon sm"),
      h("span", { text: `This is a sample problem. The reference answer is ${Object.entries(checks).map(([k, c]) => `${k} = ${fmtValue(c.expected)}`).join(", ")}.` })));
  }

  const u = trace.usage || {};
  card.append(h("div", { class: "final-stats" },
    stat(String(trace.attempts.length), trace.attempts.length === 1 ? "Attempt" : "Attempts"),
    stat(fmtDuration(trace.duration_s), "Time"),
    stat(fmtInt(u.total_tokens), "Tokens"),
    stat(fmtCost(u.cost_usd), "Cost"),
    stat(trace.model, "Model")));

  const actions = h("div", { class: "final-actions" });
  if (trace.final_answer) actions.append(actionBtn("copy", "Copy answer", () => copyText(trace.final_answer)));
  if (trace.result) actions.append(actionBtn("code", "Copy RESULT JSON", () => copyText(JSON.stringify(trace.result, null, 2))));
  if (trace.run_id) {
    const link = `${location.origin}${location.pathname}#/run/${trace.run_id}`;
    actions.append(actionBtn("link", "Copy share link", () => copyText(link)));
    if (live) actions.append(h("a", { class: "btn sm", href: `#/run/${trace.run_id}` }, icon("external", "icon sm"), "Open replay page"));
  }
  if (onRunAgain) actions.append(h("button", { class: "btn sm", type: "button", onclick: onRunAgain }, icon("refresh", "icon sm"), "Run again"));
  card.append(actions);
  return card;
}

function stat(v, k) { return h("div", { class: "stat" }, h("span", { class: "v", text: v }), h("span", { class: "k", text: k })); }

function actionBtn(iconName, label, fn) {
  const b = h("button", { class: "btn sm", type: "button" }, icon(iconName, "icon sm"), label);
  b.addEventListener("click", async () => { await fn(); flash(b, "Copied"); });
  return b;
}

// ------------------------------------------------------------------ the run view

export class RunView {
  /** opts: {live, maxAttempts, problem, onRunAgain, onFinish} */
  constructor(root, opts = {}) {
    this.root = root;
    this.opts = opts;
    this.live = !!opts.live;
    this.cards = [];
    this.reflections = [];
    this.started = Date.now();
    this.usage = { total_tokens: 0, cost_usd: 0 };
    this.finished = false;
    clear(root);

    this.statusPill = h("span", { class: "status-pill running" }, h("span", { class: "pulse-dot" }), "Running");
    this.attemptStat = stat("—", "Attempt");
    this.timeStat = stat("0.0 s", "Elapsed");
    this.tokenStat = stat("0", "Tokens");
    this.costStat = stat("$0", "Cost");
    const sub = (opts.problem || "").replace(/\s+/g, " ").slice(0, 160);
    this.stopBtn = this.live && opts.onStop
      ? h("button", { class: "btn sm danger", type: "button", onclick: () => opts.onStop() }, icon("stop", "icon sm"), "Stop") : null;
    this.head = h("section", { class: "card run-head" },
      h("div", { class: "title" }, h("h2", { text: this.live ? "Live run" : "Run" }), h("span", { class: "sub", text: sub, title: opts.problem || "" })),
      this.statusPill, this.stopBtn, h("div", { class: "run-stats" }, this.attemptStat, this.timeStat, this.tokenStat, this.costStat));

    this.pipeSteps = {};
    const pipe = h("div", { class: "pipeline" }, PIPE_STEPS.map((s) => {
      const el = h("div", { class: "pipe-step" }, h("div", { class: "pipe-bar" }),
        h("div", { class: "pipe-label" }, icon(s.icon, "icon"), h("span", { text: s.label })));
      this.pipeSteps[s.id] = el;
      return el;
    }));
    this.pipeCaption = h("div", { class: "pipe-caption" }, h("span", { class: "spinner sm" }), h("span", { text: "Starting…" }));
    this.pipeCard = h("section", { class: "card" }, pipe, this.pipeCaption);

    this.finalSlot = h("div");
    this.timeline = h("div", { class: "timeline", "aria-live": "polite" });
    this.memoryBody = h("div");
    this.memoryCard = h("section", { class: "card", hidden: true },
      h("div", { class: "card-head" }, h("h3", {}, icon("brain"), "Reflexion memory"), h("span", { class: "spacer" }),
        h("span", { class: "hint", text: "lessons carried into every later attempt" })),
      h("div", { class: "memory" }, this.memoryBody));
    append(root, [this.head, this.finalSlot, this.live ? this.pipeCard : null,
      h("div", { class: "section-title", style: { marginTop: "4px" } }, h("h3", { text: "Attempts" }), h("span", { class: "hint", text: "Thought → Action (code) → Observation → Reflection" })),
      this.timeline, this.memoryCard]);
    if (this.live) this.timer = setInterval(() => this.tick(), 200);
  }

  tick() {
    if (this.finished) return;
    this.timeStat.querySelector(".v").textContent = fmtDuration((Date.now() - this.started) / 1000);
  }

  setPipe(states, caption, spinning = true) {
    for (const s of PIPE_STEPS) this.pipeSteps[s.id].className = `pipe-step ${states[s.id] || ""}`;
    this.pipeCaption.replaceChildren(spinning ? h("span", { class: "spinner sm" }) : icon("info", "icon sm"), h("span", { text: caption }));
  }

  setUsage(u) {
    if (!u) return;
    this.usage = u;
    this.tokenStat.querySelector(".v").textContent = fmtInt(u.total_tokens);
    this.costStat.querySelector(".v").textContent = fmtCost(u.cost_usd);
  }

  addCard(number) {
    const prev = this.cards[this.cards.length - 1];
    if (prev && !prev.userToggled) prev.setOpen(false);
    const card = new AttemptCard(number, { live: this.live, prevCode: prev ? prev.data.code : null });
    this.cards.push(card);
    this.timeline.append(card.el);
    card.setOpen(true);
    return card;
  }

  renderMemory() {
    this.memoryCard.hidden = this.reflections.length === 0;
    clear(this.memoryBody).append(memoryList(this.reflections));
  }

  /** Feed one SSE event. */
  handle(kind, data) {
    const max = this.opts.maxAttempts || "?";
    const card = this.cards[this.cards.length - 1];
    if (kind === "started") {
      this.opts.maxAttempts = data.max_attempts;
    } else if (kind === "attempt_start") {
      const c = this.addCard(data.attempt);
      this.attemptStat.querySelector(".v").textContent = `${data.attempt} / ${this.opts.maxAttempts || max}`;
      this.setPipe({ llm: "active" }, data.attempt === 1 ? "The model is planning the method and writing a program…"
        : `Attempt ${data.attempt}: rewriting the program using the observation and the Reflexion memory…`);
      c.select("thought");
    } else if (kind === "action" && card) {
      card.setAction(data);
      if (!card.userToggled) card.select("code");
      this.setPipe({ llm: "done", gate: "active", run: "active" }, data.injected
        ? "Injected a demo bug, now running the program in the sandbox…" : "Checking the code and running it in the sandbox…");
    } else if (kind === "observation" && card) {
      const obs = data.observation;
      card.setObservation(obs);
      this.setUsage(data.usage);
      if (obs.ok) {
        this.setPipe({ llm: "done", gate: "done", run: "done", check: "done", reflect: "skip" }, "All self-checks passed. Writing the final answer…");
      } else {
        const more = data.attempt < (this.opts.maxAttempts || 0);
        this.setPipe(failStates(obs.kind, more ? "active" : ""),
          more ? `${kindOf(obs.kind).label}. Reflecting on what went wrong…` : `${kindOf(obs.kind).label}. No attempts left.`, more);
      }
    } else if (kind === "reflection" && card) {
      card.setReflection(data.reflection, data.nudge);
      this.reflections.push(data.reflection);
      this.renderMemory();
      this.setUsage(data.usage);
      this.setPipe(failStates(card.data.observation.kind, "done"), "Lesson stored in Reflexion memory. Starting the next attempt…");
    } else if (kind === "summarizing") {
      this.setPipe({ llm: "done", gate: "done", run: "done", check: "done", reflect: "skip" }, "Verified. Turning RESULT into a plain-English answer…");
    } else if (kind === "final") {
      this.finish(data.trace, data.score);
    } else if (kind === "error") {
      this.fail(data.message || "Something went wrong.");
    }
    if (this.live && kind !== "started") this.autoScroll();
  }

  autoScroll() {
    // Follow the run only while the user is near the bottom of the page.
    const nearBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 260;
    if (nearBottom) this.timeline.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  setStopping() {
    if (!this.stopBtn) return;
    this.stopBtn.disabled = true;
    this.stopBtn.replaceChildren(h("span", { class: "spinner sm" }), "Stopping…");
  }

  setStatus(state) {
    const map = { ok: ["ok", "check", "Verified"], bad: ["bad", "x", "Not verified"], stopped: ["stopped", "stop", "Stopped"], error: ["bad", "alert", "Error"] };
    const [cls, ic, text] = map[state];
    this.statusPill.className = `status-pill ${cls}`;
    this.statusPill.replaceChildren(icon(ic, "icon sm"), text);
  }

  finish(trace, score) {
    this.finished = true;
    clearInterval(this.timer);
    if (this.stopBtn) this.stopBtn.hidden = true;
    this.pipeCard.hidden = true;
    this.setStatus(trace.success ? "ok" : trace.stopped ? "stopped" : "bad");
    this.attemptStat.querySelector(".v").textContent = `${trace.attempts.length} / ${trace.max_attempts}`;
    this.timeStat.querySelector(".v").textContent = fmtDuration(trace.duration_s);
    this.timeStat.querySelector(".k").textContent = "Time";
    this.setUsage(trace.usage);
    // A live run built cards from events; make sure they match the saved trace.
    trace.attempts.forEach((a, i) => {
      const card = this.cards[i] || this.addCard(a.number);
      if (!card.data.observation) card.load(a);
    });
    if (!this.reflections.length) {
      this.reflections = trace.attempts.filter((a) => a.reflection).map((a) => a.reflection);
      this.renderMemory();
    }
    clear(this.finalSlot).append(finalCard(trace, score, { onRunAgain: this.opts.onRunAgain, live: this.live }));
    if (this.live) this.finalSlot.scrollIntoView({ behavior: "smooth", block: "start" });
    this.opts.onFinish?.(trace, score);
  }

  fail(message) {
    this.finished = true;
    clearInterval(this.timer);
    if (this.stopBtn) this.stopBtn.hidden = true;
    this.pipeCard.hidden = true;
    this.setStatus("error");
    clear(this.finalSlot).append(h("div", { class: "callout bad" }, icon("alert"), h("div", {}, h("b", { text: "The run stopped with an error. " }), message)));
    this.opts.onFinish?.(null, null);
  }

  /** Replay a saved trace (no animation). */
  static replay(root, trace, score) {
    const view = new RunView(root, { live: false, problem: trace.task, maxAttempts: trace.max_attempts });
    view.finish(trace, score);
    view.head.hidden = true;
    view.memoryCard.hidden = true; // the replay page shows memory in its side panel
    return view;
  }
}

export { INJECT_LABELS };
