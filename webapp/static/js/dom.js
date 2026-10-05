// Tiny DOM helpers. All text goes through textContent, so model output can never inject HTML.

const SVG_NS = "http://www.w3.org/2000/svg";

/** h("div", {class: "x", onclick: fn}, "text", child, [more]) */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key === "style" && typeof value === "object") {
      for (const [prop, v] of Object.entries(value)) {
        if (prop.startsWith("--")) el.style.setProperty(prop, v); else el.style[prop] = v;
      }
    }
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** Inline SVG icon from the sprite in index.html. */
export function icon(name, cls = "icon") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

export function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) el.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) {
  while (el.firstChild) el.firstChild.remove();
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = h("textarea", { style: { position: "fixed", opacity: "0" } });
    area.value = text;
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

/** Segmented control: options = [{value, label, icon?}]. */
export function segmented(options, value, onChange, { compact = false, label = "" } = {}) {
  const wrap = h("div", { class: `segmented${compact ? " compact" : ""}`, role: "group", "aria-label": label });
  const buttons = options.map((opt) => {
    const b = h("button", { type: "button", "aria-pressed": String(opt.value === value), title: opt.title || null },
      opt.icon ? icon(opt.icon, "icon sm") : null, opt.label);
    b.addEventListener("click", () => {
      buttons.forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      onChange(opt.value);
    });
    return b;
  });
  append(wrap, buttons);
  wrap.setDisabled = (disabled) => buttons.forEach((b) => { b.disabled = disabled; });
  wrap.setValue = (v) => buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(options[i].value === v)));
  return wrap;
}

/** Tabs bound to panes: tabs = [{id, label, icon, count?}]; returns {el, select(id)}. */
export function tabBar(tabs, onSelect) {
  const el = h("div", { class: "tabs", role: "tablist" });
  const buttons = new Map();
  for (const t of tabs) {
    const b = h("button", { type: "button", role: "tab", "aria-selected": "false", dataset: { tab: t.id } },
      t.icon ? icon(t.icon, "icon sm") : null, t.label);
    b.addEventListener("click", () => select(t.id, true));
    buttons.set(t.id, b);
    el.append(b);
  }
  function select(id, byUser = false) {
    for (const [key, b] of buttons) b.setAttribute("aria-selected", String(key === id));
    onSelect(id, byUser);
  }
  function setBadge(id, text) {
    const b = buttons.get(id);
    if (!b) return;
    b.querySelector(".count")?.remove();
    if (text) b.append(h("span", { class: "count", text }));
  }
  function setVisible(id, visible) {
    const b = buttons.get(id);
    if (b) b.hidden = !visible;
  }
  return { el, select, setBadge, setVisible };
}
