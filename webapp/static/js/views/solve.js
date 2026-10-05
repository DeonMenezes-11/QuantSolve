// Solve page: pick or write a problem, choose options, watch the loop run live.

import { api, followRun } from "../api.js";
import { h, icon, clear, segmented } from "../dom.js";
import { RunView } from "../runview.js";

const OPTS_KEY = "qs-opts", JOB_KEY = "qs-job", LAST_KEY = "qs-last", HERO_KEY = "qs-hero-hidden";

const INJECT_HELP = {
  none: { icon: "info", cls: "", text: "The model's program runs exactly as written." },
  crash: { icon: "bug", cls: "warn", text: "Demo: a variable in attempt 1 is misspelled, so it crashes with a NameError. Watch the traceback drive the fix." },
  logic: { icon: "bug", cls: "warn", text: "Demo: an off-by-one or a flipped +/− is injected into attempt 1. The program still runs; only its own assert self-checks can notice." },
};

const QUICK_DEMOS = [
  { task: "income_tax", inject: "crash", icon: "bug", color: "var(--k-runtime)", title: "Fix an injected crash",
    text: "Income tax for three salaries. Attempt 1 gets a typo; the traceback guides the repair." },
  { task: "eoq_discount", inject: "none", icon: "box", color: "var(--accent)", title: "Solve a business problem",
    text: "Best order quantity with bulk discounts, verified by the program's own checks." },
  { task: "sip_stepup", inject: "logic", icon: "alert", color: "var(--k-assertion)", title: "Hide a logic bug",
    text: "An off-by-one is slipped into a SIP calculation. Do the self-checks catch it?" },
];

const store = {
  get(key, fallback, session = false) {
    try { const v = (session ? sessionStorage : localStorage).getItem(key); return v ? JSON.parse(v) : fallback; }
    catch { return fallback; }
  },
  set(key, value, session = false) {
    try { (session ? sessionStorage : localStorage).setItem(key, JSON.stringify(value)); } catch { /* ignore */ }
  },
  del(key, session = false) { try { (session ? sessionStorage : localStorage).removeItem(key); } catch { /* ignore */ } },
};

export async function mount(root, _params, ctx) {
  const { meta, tasks } = ctx;
  const saved = store.get(OPTS_KEY, {});
  const opts = {
    model: meta.models.includes(saved.model) ? saved.model : meta.default_model,
    attempts: Math.min(8, Math.max(1, saved.attempts || meta.max_attempts)),
    inject: ["none", "crash", "logic"].includes(saved.inject) ? saved.inject : "none",
  };
  let selected = null, running = false, jobId = null, stream = null, view = null;
  const saveOpts = () => store.set(OPTS_KEY, opts);

  // ---------------------------------------------------------------- hero
  const hero = store.get(HERO_KEY, false) ? null : h("section", { class: "hero" },
    h("div", { class: "hero-text" },
      h("span", { class: "eyebrow", text: "Self-correcting code execution" }),
      h("h1", {}, "Ask a numbers question. Get an answer that ", h("span", { class: "grad", text: "checked itself." })),
      h("p", { text: "QuantSolve writes a Python program for your problem, runs it in a locked-down sandbox, " +
        "verifies the result with its own assert checks and, when something breaks, reflects on the error and tries again." })),
    h("div", { class: "hero-steps", "aria-hidden": "true" },
      heroStep("spark", "Plan & write code"), h("span", { class: "hero-arrow" }, icon("chevron-right", "icon sm")),
      heroStep("shield", "Run safely"), h("span", { class: "hero-arrow" }, icon("chevron-right", "icon sm")),
      heroStep("check", "Self-check"), h("span", { class: "hero-arrow" }, icon("chevron-right", "icon sm")),
      heroStep("brain", "Reflect & fix")),
    h("button", { class: "icon-btn hero-close", type: "button", "aria-label": "Hide introduction", title: "Hide introduction",
      onclick: () => { store.set(HERO_KEY, true); hero.remove(); } }, icon("x", "icon sm")));

  // ---------------------------------------------------------------- composer: examples
  const detail = h("div", { class: "example-detail", hidden: true });
  const exampleButtons = tasks.map((t) => {
    const b = h("button", { class: "example", type: "button", "aria-pressed": "false", title: `${t.title}: ${t.blurb}` },
      h("span", { class: "ex-icon" }, icon(t.icon, "icon sm")),
      h("span", { class: "ex-text" }, h("span", { class: "ex-title", text: t.short }), h("span", { class: "ex-cat", text: t.category })));
    b.addEventListener("click", () => pickExample(t));
    return b;
  });

  // ---------------------------------------------------------------- composer: problem box
  const textarea = h("textarea", { id: "problem", rows: "6", spellcheck: "true", "aria-label": "Problem",
    placeholder: "e.g. A machine costs Rs 8,00,000 and depreciates 15% a year (written-down value). Find its book value after 6 years. RESULT keys: book_value." });
  const counter = h("span", { text: "0 / 6000" });
  const scoredTag = h("span", { class: "scored-tag", hidden: true }, icon("target", "icon sm"), "Scored against reference");
  const clearBtn = h("button", { class: "btn sm ghost", type: "button", title: "Clear the problem", onclick: () => {
    textarea.value = ""; onInput(); textarea.focus(); } }, icon("eraser", "icon sm"), "Clear");
  const problemBox = h("div", { class: "problem-box" }, textarea,
    h("div", { class: "problem-meta" }, counter, scoredTag, h("span", { class: "spacer" }), clearBtn));

  // ---------------------------------------------------------------- composer: options
  const modelSeg = segmented(meta.models.map((m) => ({ value: m, label: m })), opts.model,
    (v) => { opts.model = v; saveOpts(); }, { label: "Model" });
  const attemptsOut = h("output", { text: String(opts.attempts), "aria-live": "polite" });
  const minus = h("button", { type: "button", "aria-label": "Fewer attempts", text: "−" });
  const plus = h("button", { type: "button", "aria-label": "More attempts", text: "+" });
  const setAttempts = (n) => {
    opts.attempts = Math.min(8, Math.max(1, n));
    attemptsOut.textContent = String(opts.attempts);
    minus.disabled = running || opts.attempts <= 1;
    plus.disabled = running || opts.attempts >= 8;
    saveOpts();
  };
  minus.addEventListener("click", () => setAttempts(opts.attempts - 1));
  plus.addEventListener("click", () => setAttempts(opts.attempts + 1));
  const stepper = h("div", { class: "stepper", role: "group", "aria-label": "Maximum attempts" }, minus, attemptsOut, plus);
  const injectHelp = h("div", { class: "option-help" });
  const renderInjectHelp = () => {
    const help = INJECT_HELP[opts.inject];
    injectHelp.className = `option-help ${help.cls}`;
    injectHelp.replaceChildren(icon(help.icon, "icon sm"), h("span", { text: help.text }));
  };
  const injectSeg = segmented([
    { value: "none", label: "None" },
    { value: "crash", label: "Crash", icon: "zap" },
    { value: "logic", label: "Logic", icon: "bug" },
  ], opts.inject, (v) => { opts.inject = v; saveOpts(); renderInjectHelp(); }, { label: "Demo bug" });
  renderInjectHelp();

  // ---------------------------------------------------------------- composer: footer
  const solveBtn = h("button", { class: "btn primary big block", type: "button" });
  const keyHint = h("div", { class: "hint" }, "Press ", h("kbd", { text: navigator.platform.includes("Mac") ? "⌘" : "Ctrl" }), " + ",
    h("kbd", { text: "Enter" }), " to solve · ", h("kbd", { text: "/" }), " to jump here");
  const keyWarning = meta.api_key ? null : h("div", { class: "callout bad" }, icon("key"),
    h("div", {}, h("b", { text: "No OpenAI API key. " }), "Copy ", h("code", { text: ".env.example" }), " to ",
      h("code", { text: ".env" }), ", paste your key and restart. History, Results and How it works still work."));

  const composer = h("section", { class: "card composer", "aria-label": "Problem composer" },
    h("div", { class: "composer-body" },
      h("div", { class: "field" },
        h("div", { class: "section-title" }, h("span", { class: "step-num", text: "1" }), h("span", { class: "label", text: "Pick an example" }),
          h("span", { class: "hint", text: "or write your own below" })),
        h("div", { class: "examples" }, exampleButtons), detail),
      h("div", { class: "field" },
        h("div", { class: "section-title" }, h("span", { class: "step-num", text: "2" }), h("label", { class: "label", for: "problem", text: "Your problem" })),
        problemBox,
        h("p", { class: "hint", text: "State every rule and the RESULT keys you want back. The more precise the problem, the better the checks." })),
      h("div", { class: "field" },
        h("div", { class: "section-title" }, h("span", { class: "step-num", text: "3" }), h("span", { class: "label", text: "Options" })),
        h("div", { class: "options-grid" },
          h("div", { class: "option-row" }, h("span", { class: "hint", text: "Model" }), modelSeg),
          h("div", { class: "option-row" }, h("span", { class: "hint", text: "Max attempts" }), stepper)),
        h("div", { class: "option-row" }, h("div", { class: "row-head" }, h("span", { class: "hint", text: "Demo: inject a bug into attempt 1" })), injectSeg, injectHelp))),
    h("div", { class: "composer-foot" }, keyWarning, solveBtn, keyHint));

  const panel = h("div", { class: "run-panel" });
  root.append(hero || "", h("div", { class: "solve-grid" }, composer, panel));

  // ---------------------------------------------------------------- behaviour
  function heroStep(iconName, text) { return h("div", { class: "hero-step" }, icon(iconName, "icon sm"), text); }

  function pickExample(t) {
    if (running) return;
    textarea.value = t.problem;
    onInput();
    detail.hidden = false;
    detail.replaceChildren(icon("info", "icon sm"), h("span", {}, h("b", { text: `${t.title}. ` }), t.blurb, " Returns ", h("code", { text: t.keys.join(", ") }), "."));
  }

  function onInput() {
    const text = textarea.value;
    counter.textContent = `${text.length} / 6000`;
    counter.style.color = text.length > 6000 ? "var(--bad)" : "";
    selected = tasks.find((t) => t.problem.trim() === text.trim()) || null;
    exampleButtons.forEach((b, i) => b.setAttribute("aria-pressed", String(tasks[i] === selected)));
    scoredTag.hidden = !selected;
    if (!selected) detail.hidden = true;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(360, Math.max(150, textarea.scrollHeight + 2))}px`;
  }
  textarea.addEventListener("input", onInput);

  function setRunning(on, stopping = false) {
    running = on;
    textarea.disabled = on;
    exampleButtons.forEach((b) => { b.disabled = on; });
    modelSeg.setDisabled(on);
    injectSeg.setDisabled(on);
    setAttempts(opts.attempts);
    solveBtn.disabled = (!on && !meta.api_key) || stopping;
    solveBtn.className = `btn big block ${on ? "danger" : "primary"}`;
    solveBtn.replaceChildren(...(on
      ? (stopping ? [h("span", { class: "spinner sm" }), "Stopping after this step…"] : [icon("stop"), "Stop"])
      : [icon("play"), "Solve", h("kbd", { text: navigator.platform.includes("Mac") ? "⌘↵" : "Ctrl ↵" })]));
  }

  async function solve() {
    if (running) return;
    const problem = textarea.value.trim();
    if (!problem) { ctx.toast("Write a problem or pick an example first.", "bad"); textarea.focus(); return; }
    if (problem.length > 6000) { ctx.toast("The problem is longer than 6000 characters.", "bad"); return; }
    if (!meta.api_key) { ctx.toast("Add OPENAI_API_KEY to .env and restart the server to solve problems.", "bad"); return; }
    setRunning(true);
    try {
      const res = await api("/api/runs", { method: "POST",
        body: { problem, model: opts.model, max_attempts: opts.attempts, inject: opts.inject } });
      follow(res.job_id, problem, { ...opts });
    } catch (err) {
      setRunning(false);
      ctx.toast(err.message, "bad", 6000);
    }
  }

  function follow(id, problem, runOpts) {
    jobId = id;
    store.set(JOB_KEY, { jobId: id, problem, opts: runOpts }, true);
    view = new RunView(panel, { live: true, problem, maxAttempts: runOpts.attempts, onRunAgain: () => solve(), onStop: () => stop(),
      onFinish: (trace) => {
        setRunning(false);
        store.del(JOB_KEY, true);
        if (!trace) return;
        store.set(LAST_KEY, trace.run_id, true);
        if (trace.success) ctx.toast(`Verified in ${trace.attempts.length} attempt${trace.attempts.length === 1 ? "" : "s"}.`, "ok");
        else if (trace.stopped) ctx.toast("Run stopped.", "info");
        else ctx.toast("No verified answer within the attempt budget.", "bad");
      } });
    stream = followRun(id, {
      event: (kind, data) => view.handle(kind, data),
      end: () => { if (running) setRunning(false); store.del(JOB_KEY, true); },
      lost: (err) => { view.fail(err.message); setRunning(false); store.del(JOB_KEY, true); },
    });
  }

  async function stop() {
    if (!jobId || !running) return;
    setRunning(true, true);
    view?.setStopping();
    try {
      await api(`/api/runs/${jobId}/stop`, { method: "POST" });
      ctx.toast("Stopping after the current step…", "info");
    } catch (err) { ctx.toast(err.message, "bad"); }
  }

  solveBtn.addEventListener("click", () => (running ? stop() : solve()));
  const onKey = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); solve(); }
  };
  document.addEventListener("keydown", onKey);

  function emptyState() {
    clear(panel).append(h("section", { class: "card run-empty" },
      loopArt(),
      h("div", {}, h("h2", { text: "Watch the loop think, run, check and fix" }),
        h("p", { text: "Pick an example on the left, or start with one of these one-click demos. Every step appears here live: the model's plan, its program, what the sandbox saw, and the lesson it took from each failure." })),
      h("div", { class: "quick-demos" }, QUICK_DEMOS.map((d) => {
        const task = tasks.find((t) => t.id === d.task);
        return h("button", { class: "quick-demo", type: "button", disabled: !meta.api_key || !task, onclick: () => {
          pickExample(task);
          opts.inject = d.inject;
          saveOpts();
          injectSeg.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String(["none", "crash", "logic"][i] === d.inject)));
          renderInjectHelp();
          solve();
        } },
        h("span", { class: "qd-icon", style: { background: `color-mix(in srgb, ${d.color} 14%, transparent)`, color: d.color } }, icon(d.icon)),
        h("span", {}, h("b", { text: d.title }), h("span", { text: d.text })));
      })),
      h("p", { class: "hint" }, "Saved runs live in ", h("a", { href: "#/history", text: "History" }), "; benchmark numbers in ",
        h("a", { href: "#/results", text: "Results" }), ".")));
  }

  // ---------------------------------------------------------------- initial state
  setRunning(false);
  onInput();
  const pending = store.get(JOB_KEY, null, true);
  const last = store.get(LAST_KEY, null, true);
  const prefill = store.get("qs-prefill", null, true);
  if (prefill && !(pending && pending.jobId)) {
    store.del("qs-prefill", true);
    textarea.value = prefill; onInput();
    emptyState();
    textarea.focus();
  } else if (pending && pending.jobId) {
    textarea.value = pending.problem; onInput();
    try {
      const status = await api(`/api/runs/${pending.jobId}`);
      setRunning(!status.done);
      follow(pending.jobId, pending.problem, pending.opts || opts);
    } catch {
      store.del(JOB_KEY, true);
      emptyState();
    }
  } else if (last) {
    try {
      const saved = await api(`/api/history/${encodeURIComponent(last)}`);
      textarea.value = saved.trace.task; onInput();
      view = new RunView(panel, { live: false, problem: saved.trace.task, onRunAgain: () => solve() });
      view.finish(saved.trace, saved.score);
    } catch { store.del(LAST_KEY, true); emptyState(); }
  } else {
    emptyState();
  }

  return () => {
    document.removeEventListener("keydown", onKey);
    stream?.close();
    if (view?.timer) clearInterval(view.timer);
  };
}

function loopArt() {
  const wrap = h("div", { class: "loop-art", "aria-hidden": "true" });
  // Static illustration (no user data).
  wrap.innerHTML = `
  <svg viewBox="0 0 420 200" class="diagram">
    <defs><marker id="ah-flow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0L10 5L0 10z" style="fill:var(--accent)"/></marker>
      <marker id="ah-fail" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0L10 5L0 10z" style="fill:var(--bad)"/></marker></defs>
    <g style="color:var(--accent)">
      <path class="edge flow" d="M118 55 H170" marker-end="url(#ah-flow)"/>
      <path class="edge flow" d="M268 55 H300" marker-end="url(#ah-flow)"/>
    </g>
    <g style="color:var(--bad)">
      <path class="edge fail" d="M353 82 V118" marker-end="url(#ah-fail)"/>
      <path class="edge fail" d="M300 145 H268" marker-end="url(#ah-fail)"/>
      <path class="edge fail" d="M170 145 H120 Q66 145 66 100 V86" marker-end="url(#ah-fail)"/>
    </g>
    <g class="node llm"><rect x="14" y="30" width="104" height="52" rx="12"/><text x="66" y="54" text-anchor="middle">Plan &amp; code</text><text class="sub" x="66" y="70" text-anchor="middle">LLM</text></g>
    <g class="node"><rect x="170" y="30" width="98" height="52" rx="12"/><text x="219" y="54" text-anchor="middle">Sandbox</text><text class="sub" x="219" y="70" text-anchor="middle">exec() in a child</text></g>
    <g class="node ok"><rect x="300" y="30" width="106" height="52" rx="12"/><text x="353" y="54" text-anchor="middle">Self-checks</text><text class="sub" x="353" y="70" text-anchor="middle">asserts + RESULT</text></g>
    <g class="node bad"><rect x="300" y="120" width="106" height="52" rx="12"/><text x="353" y="144" text-anchor="middle">Failure</text><text class="sub" x="353" y="160" text-anchor="middle">traceback</text></g>
    <g class="node mem"><rect x="170" y="120" width="98" height="52" rx="12"/><text x="219" y="144" text-anchor="middle">Reflect</text><text class="sub" x="219" y="160" text-anchor="middle">lesson → memory</text></g>
  </svg>`;
  return wrap;
}
