// App shell: hash router, theme, API status, keyboard shortcuts and toasts.

import { api, OFFLINE_MESSAGE } from "./api.js";
import { h, icon, clear, $ } from "./dom.js";
import * as solveView from "./views/solve.js";
import * as historyView from "./views/history.js";
import * as runView from "./views/run.js";
import * as resultsView from "./views/results.js";
import * as howView from "./views/how.js";

const ROUTES = [
  { pattern: /^\/solve$/, view: solveView, nav: "solve", title: "Solve" },
  { pattern: /^\/history$/, view: historyView, nav: "history", title: "History" },
  { pattern: /^\/run\/([\w.-]+)$/, view: runView, nav: "history", title: "Run replay" },
  { pattern: /^\/results$/, view: resultsView, nav: "results", title: "Results" },
  { pattern: /^\/how$/, view: howView, nav: "how", title: "How it works" },
];

const main = $("#main");
const ctx = { meta: null, tasks: [], toast, go: (hash) => { location.hash = hash; } };
let cleanup = null;

// ------------------------------------------------------------------ toasts
function toast(message, type = "info", ms = 3800) {
  const iconName = type === "ok" ? "check" : type === "bad" ? "alert" : "info";
  const el = h("div", { class: `toast ${type}` }, icon(iconName), h("div", { text: message }));
  $("#toasts").append(el);
  setTimeout(() => { el.classList.add("leave"); setTimeout(() => el.remove(), 220); }, ms);
}

// ------------------------------------------------------------------ theme
const THEME_ICONS = { system: "monitor", light: "sun", dark: "moon" };
const THEME_NEXT = { system: "light", light: "dark", dark: "system" };
const media = matchMedia("(prefers-color-scheme: dark)");

function applyTheme(pref) {
  const dark = pref === "dark" || (pref === "system" && media.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.themePref = pref;
  const btn = $("#theme-btn");
  btn.replaceChildren(icon(THEME_ICONS[pref]));
  const label = `Theme: ${pref === "system" ? "match system" : pref}. Click to change.`;
  btn.title = label;
  btn.setAttribute("aria-label", label);
}

function initTheme() {
  let pref = "system";
  try { pref = localStorage.getItem("qs-theme") || "system"; } catch { /* storage blocked */ }
  applyTheme(pref);
  $("#theme-btn").addEventListener("click", () => {
    pref = THEME_NEXT[document.documentElement.dataset.themePref || "system"];
    try { localStorage.setItem("qs-theme", pref); } catch { /* ignore */ }
    applyTheme(pref);
    toast(`Theme: ${pref === "system" ? "matching your system" : pref}`, "info", 1600);
  });
  media.addEventListener("change", () => {
    if ((document.documentElement.dataset.themePref || "system") === "system") applyTheme("system");
  });
}

// ------------------------------------------------------------------ nav
function initNav() {
  const nav = $("#nav"), toggle = $("#nav-toggle");
  const close = () => { nav.classList.remove("open"); toggle.setAttribute("aria-expanded", "false"); };
  toggle.addEventListener("click", () => {
    const open = !nav.classList.contains("open");
    nav.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
  });
  nav.addEventListener("click", (e) => { if (e.target.closest("a")) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}

function setActiveNav(name) {
  for (const a of document.querySelectorAll("#nav a")) {
    const active = a.dataset.route === name;
    a.classList.toggle("active", active);
    if (active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
}

// ------------------------------------------------------------------ router
async function route() {
  const path = ((location.hash || "#/solve").slice(1) || "/solve").split("?")[0]; // ?query is read by the view
  const match = ROUTES.map((r) => ({ r, m: r.pattern.exec(path) })).find((x) => x.m);
  if (!match) { location.replace("#/solve"); return; }
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  $("#nav").classList.remove("open");
  $("#nav-toggle").setAttribute("aria-expanded", "false");
  setActiveNav(match.r.nav);
  document.title = `${match.r.title} · QuantSolve`;
  clear(main);
  main.classList.remove("enter");
  void main.offsetWidth; // restart the entry animation
  main.classList.add("enter");
  window.scrollTo({ top: 0 });
  try {
    cleanup = (await match.r.view.mount(main, match.m.slice(1), ctx)) || null;
  } catch (err) {
    console.error(err);
    clear(main).append(h("div", { class: "card empty" }, h("div", { class: "icon-wrap" }, icon("alert", "icon xl")),
      h("h2", { text: "This page could not be loaded" }), h("p", { text: err.message || String(err) }),
      h("a", { class: "btn", href: "#/solve" }, icon("arrow-left", "icon sm"), "Back to Solve")));
  }
}

// ------------------------------------------------------------------ server status
let online = true;

function renderPill() {
  const pill = $("#api-pill");
  pill.hidden = false;
  if (!online) {
    pill.textContent = "Server offline";
    pill.title = OFFLINE_MESSAGE;
    pill.classList.add("bad");
    return;
  }
  pill.textContent = ctx.meta.api_key ? "OpenAI connected" : "API key missing";
  pill.title = ctx.meta.api_key ? `Default model: ${ctx.meta.default_model}` : "Add OPENAI_API_KEY to .env and restart the server";
  pill.classList.toggle("bad", !ctx.meta.api_key);
}

/** `announce`: toast the change (the poller does; failed API calls are toasted by the caller). */
function setOnline(value, announce = false) {
  if (value === online) return;
  online = value;
  renderPill();
  if (value) toast("Reconnected to the QuantSolve server.", "ok");
  else if (announce) toast(OFFLINE_MESSAGE, "bad", 7000);
}

function initServerStatus() {
  renderPill();
  window.addEventListener("qs:online", () => setOnline(true));
  window.addEventListener("qs:offline", () => setOnline(false));
  // Poll lightly so the pill notices a stopped (or restarted) server without a click.
  setInterval(async () => {
    try {
      const meta = await fetch("/api/meta", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null));
      if (meta) { ctx.meta = { ...ctx.meta, ...meta }; setOnline(true); renderPill(); }
    } catch { setOnline(false, true); }
  }, 8000);
}

// ------------------------------------------------------------------ boot
async function boot() {
  initTheme();
  initNav();
  try {
    [ctx.meta, ctx.tasks] = await Promise.all([api("/api/meta"), api("/api/tasks")]);
  } catch (err) {
    clear(main).append(h("div", { class: "card empty" }, h("div", { class: "icon-wrap" }, icon("alert", "icon xl")),
      h("h2", { text: "Cannot reach the QuantSolve server" }),
      h("p", { text: "Start it with python3 web.py in the project folder, then reload this page." }),
      h("button", { class: "btn primary", type: "button", onclick: () => location.reload() }, icon("refresh", "icon sm"), "Reload")));
    return;
  }
  initServerStatus();
  $("#footer-course").textContent = ctx.meta.course;
  $("#footer-team").replaceChildren(...ctx.meta.team.map((m) => h("span", {}, h("b", { text: m.name }), ` · ${m.roll} · ${m.batch}`)));

  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
    if (e.key === "/" && !typing) {
      const box = $("#problem");
      if (box) { e.preventDefault(); box.focus(); }
    }
  });
  window.addEventListener("hashchange", route);
  route();
}

boot();
