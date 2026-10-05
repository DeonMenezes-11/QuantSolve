// How it works: the loop diagram, the three ideas behind it, the sandbox layers, the failure
// kinds and the team.

import { h, icon } from "../dom.js";
import { KINDS } from "../format.js";

const SHOWCASE = "20261004-235610_sip_stepup_inject-logic";

const STAGE = { blocked: "safety gate", syntax: "safety gate", runtime: "sandbox run", timeout: "sandbox run",
  assertion: "self-checks", contract: "self-checks", ok: "self-checks" };

export function mount(root, _params, ctx) {
  const diagram = h("div", { class: "diagram-scroll" });
  // Static diagram markup (no user data).
  diagram.innerHTML = `
  <svg class="diagram" viewBox="0 0 990 330" role="img" aria-label="The QuantSolve loop">
    <defs>
      <marker id="arr-flow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" style="fill:var(--accent)"/></marker>
      <marker id="arr-fail" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" style="fill:var(--bad)"/></marker>
      <marker id="arr-pass" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" style="fill:var(--k-ok)"/></marker>
    </defs>
    <path class="edge flow" d="M160 62 H204" marker-end="url(#arr-flow)"/>
    <path class="edge flow" d="M350 62 H394" marker-end="url(#arr-flow)"/>
    <path class="edge flow" d="M540 62 H584" marker-end="url(#arr-flow)"/>
    <path class="edge flow" d="M730 62 H824" marker-end="url(#arr-flow)"/>
    <path class="edge pass" d="M900 94 V244" marker-end="url(#arr-pass)"/>
    <path class="edge fail" d="M470 94 V244" marker-end="url(#arr-fail)"/>
    <path class="edge fail" d="M640 94 L532 244" marker-end="url(#arr-fail)"/>
    <path class="edge fail" d="M850 94 Q 760 270 546 286" marker-end="url(#arr-fail)"/>
    <path class="edge flow" d="M400 282 H356" marker-end="url(#arr-flow)"/>
    <path class="edge flow" d="M280 250 V100" marker-end="url(#arr-flow)"/>
    <text class="elabel" x="563" y="50" text-anchor="middle" style="fill:var(--accent)">allowed</text>
    <text class="elabel" x="778" y="50" text-anchor="middle" style="fill:var(--accent)">ran</text>
    <text class="elabel" x="890" y="175" text-anchor="end" style="fill:var(--k-ok)">all checks pass</text>
    <text class="elabel" x="478" y="175" style="fill:var(--bad)">blocked</text>
    <text class="elabel" x="614" y="148" style="fill:var(--bad)">crashed / timed out</text>
    <text class="elabel" x="676" y="276" style="fill:var(--bad)">a check failed</text>
    <text class="elabel" x="378" y="272" text-anchor="middle" style="fill:var(--accent)">lesson</text>
    <text class="elabel" x="290" y="180" style="fill:var(--accent)">next attempt</text>
    <g class="node"><rect x="20" y="30" width="140" height="64" rx="14"/><text x="90" y="58" text-anchor="middle">Your problem</text><text class="sub" x="90" y="76" text-anchor="middle">plain English + keys</text></g>
    <g class="node llm"><rect x="210" y="30" width="140" height="64" rx="14"/><text x="280" y="58" text-anchor="middle">Plan &amp; write code</text><text class="sub" x="280" y="76" text-anchor="middle">LLM · Thought + Action</text></g>
    <g class="node"><rect x="400" y="30" width="140" height="64" rx="14"/><text x="470" y="58" text-anchor="middle">Safety gate</text><text class="sub" x="470" y="76" text-anchor="middle">static AST checks</text></g>
    <g class="node"><rect x="590" y="30" width="140" height="64" rx="14"/><text x="660" y="58" text-anchor="middle">Sandbox run</text><text class="sub" x="660" y="76" text-anchor="middle">restricted exec() child</text></g>
    <g class="node"><rect x="830" y="30" width="140" height="64" rx="14"/><text x="900" y="58" text-anchor="middle">Self-checks</text><text class="sub" x="900" y="76" text-anchor="middle">≥ 2 asserts + RESULT</text></g>
    <g class="node mem"><rect x="210" y="250" width="140" height="64" rx="14"/><text x="280" y="278" text-anchor="middle">Reflexion memory</text><text class="sub" x="280" y="296" text-anchor="middle">every lesson so far</text></g>
    <g class="node bad"><rect x="400" y="250" width="140" height="64" rx="14"/><text x="470" y="278" text-anchor="middle">Reflect</text><text class="sub" x="470" y="296" text-anchor="middle">LLM · diagnosis + plan</text></g>
    <g class="node ok"><rect x="830" y="250" width="140" height="64" rx="14"/><text x="900" y="278" text-anchor="middle">Verified answer</text><text class="sub" x="900" y="296" text-anchor="middle">plain-English summary</text></g>
  </svg>`;

  const concepts = [
    { icon: "spark", color: "var(--accent)", title: "ReAct: reason, then act",
      text: "Each attempt is one Thought → Action → Observation step.",
      bullets: ["Thought: the method, formulas and which invariants to check", "Action: a complete Python program", "Observation: the sandbox result, or the failure kind with a cleaned traceback"] },
    { icon: "brain", color: "var(--k-assertion)", title: "Reflexion: learn from failure",
      text: "After a failure the model writes a short verbal reflection that is kept in memory.",
      bullets: ["Diagnosis: what went wrong and on which line", "Lesson: a general rule, written to itself", "Every later attempt sees all lessons; a loop guard nudges it when it repeats itself"] },
    { icon: "check", color: "var(--k-ok)", title: "Self-verification with asserts",
      text: "The program must check its own answer, so logic bugs can surface, not just crashes.",
      bullets: ["At least two assert statements are required", "Each compares quantities computed two different ways", "Honest limit: checks written by the same model can miss bugs (see Results)"] },
  ];

  const layers = [
    ["AST safety gate", "Only allow-listed imports (math, statistics, fractions, decimal, itertools, numpy …). eval, exec, open, getattr and every underscore attribute are rejected before anything runs."],
    ["Restricted builtins", "The program sees a curated set of builtins, not the real ones."],
    ["Guarded import", "Imports are re-checked against the allow-list while the program runs."],
    ["Separate process", "A fresh 'spawn' child with its environment wiped, so the API key is not even there."],
    ["Resource limits", "A CPU-time limit and a 1 GB memory watchdog."],
    ["Wall-clock timeout", "The child is killed after the time limit (10 s by default)."],
  ];

  root.append(
    h("section", { class: "how-hero" }, h("span", { class: "eyebrow", text: "How it works" }),
      h("h1", { text: "A program that checks its own answer, and fixes itself when it can't" }),
      h("p", { text: "QuantSolve uses program-aided reasoning: the language model never states the final number itself. It writes Python that computes and verifies the answer, and the loop below repairs that program from real execution feedback." })),
    h("section", { class: "card diagram-card", style: { marginBottom: "var(--s6)" } }, diagram,
      h("div", { class: "legend", style: { justifyContent: "center", marginTop: "var(--s3)" } },
        h("span", {}, h("i", { style: { background: "var(--accent)" } }), "normal flow"),
        h("span", {}, h("i", { style: { background: "var(--bad)" } }), "failure → observation"),
        h("span", {}, h("i", { style: { background: "var(--k-ok)" } }), "success"))),
    h("div", { class: "concepts", style: { marginBottom: "var(--s6)" } }, concepts.map((c) => h("section", { class: "card concept" },
      h("div", { class: "c-icon", style: { background: `color-mix(in srgb, ${c.color} 14%, transparent)`, color: c.color } }, icon(c.icon, "icon lg")),
      h("h3", { text: c.title }), h("p", { text: c.text }), h("ul", {}, c.bullets.map((b) => h("li", { text: b }))),
      h("a", { class: "more-link", href: `#/run/${SHOWCASE}` }, "See it in a real run", icon("arrow-right", "icon sm"))))),
    h("div", { class: "grid-2", style: { marginBottom: "var(--s6)" } },
      h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, icon("shield"), "Six layers of sandboxing")),
        h("div", { class: "card-pad layers" }, layers.map(([t, d], i) => h("div", { class: "layer" },
          h("span", { class: "l-num", text: String(i + 1) }), h("div", {}, h("b", { text: t }), h("span", { text: d }))))),
        h("p", { class: "note", style: { padding: "0 var(--s5) var(--s5)" } }, "Restricted ", h("code", { text: "exec()" }),
          " alone is not a security boundary, which is why the layers stack. ", h("a", { href: "#/results", text: "See the safety evaluation →" }))),
      h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, icon("terminal"), "What the model is told when something fails")),
        h("div", { class: "card-pad kinds" }, Object.entries(KINDS).filter(([k]) => k !== "stopped").map(([k, v]) =>
          h("div", { class: "kind-card", style: { "--c": `var(--k-${k})` } }, h("span", { class: "ki" }, icon(v.icon, "icon sm")),
            h("div", {}, h("b", { text: v.label }), h("span", { text: `${v.explain} (${STAGE[k]})` }))))))),
    h("section", { class: "card card-pad", style: { marginBottom: "var(--s6)" } },
      h("div", { class: "section-title" }, h("h2", { text: "Team" }), h("span", { class: "hint", text: ctx.meta.course })),
      h("div", { class: "team" }, ctx.meta.team.map((m) => h("div", { class: "member" },
        h("div", { class: "avatar", text: m.name.split(" ").map((p) => p[0]).join("") }),
        h("div", {}, h("b", { text: m.name }), h("div", { class: "hint", text: `Roll no ${m.roll} · Batch ${m.batch}` }))))),
      h("div", { class: "meta-bar", style: { marginTop: "var(--s4)" } },
        ["Python 3.13", `OpenAI ${ctx.meta.default_model}`, "FastAPI + Server-Sent Events", "Vanilla JS, no framework", "multiprocessing sandbox"]
          .map((t) => h("span", { class: "chip", text: t })))),
    h("section", { class: "card card-pad", style: { display: "flex", alignItems: "center", gap: "var(--s4)", flexWrap: "wrap" } },
      h("div", { style: { flex: "1 1 300px" } }, h("h2", { text: "Try it yourself" }),
        h("p", { class: "muted", style: { marginTop: "4px" }, text: "Inject a bug into the first attempt and watch the loop find and fix it." })),
      h("a", { class: "btn primary big", href: "#/solve" }, icon("zap"), "Open the solver")));
}
