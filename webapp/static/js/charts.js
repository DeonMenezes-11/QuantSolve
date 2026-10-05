// Dependency-free SVG charts. Colours come from CSS variables so both themes work.

import { svg, h } from "./dom.js";

/** Draw a chart at the container's real pixel width (crisp, legible text) and redraw on resize. */
export function responsiveChart(draw, { minWidth = 260 } = {}) {
  const box = h("div", { class: "chart-box" });
  let last = 0;
  const render = () => {
    const width = Math.max(minWidth, Math.floor(box.clientWidth));
    if (!box.clientWidth || width === last) return;
    last = width;
    box.replaceChildren(draw(width));
  };
  new ResizeObserver(render).observe(box);
  return box;
}

function wrapLabel(label, max = 12) {
  const words = String(label).split(" ");
  const lines = [];
  let line = "";
  for (const w of words) {
    if ((line + " " + w).trim().length > max && line) { lines.push(line); line = w; }
    else line = (line + " " + w).trim();
  }
  if (line) lines.push(line);
  return lines.slice(0, 3);
}

function niceMax(value) {
  if (value <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(value)));
  const f = value / exp;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp;
}

/** Vertical bars. items: [{label, value, color, display, title}] */
export function barChart(items, { max, ticks = 4, format = (v) => v, height = 250, width = 460 } = {}) {
  const top = 26, bottom = 52, left = 40, right = 8;
  const plotH = height - top - bottom, plotW = width - left - right;
  const vmax = max ?? niceMax(Math.max(...items.map((d) => d.value), 0));
  const band = plotW / items.length;
  const barW = Math.min(64, band * 0.58);
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${width} ${height}`, role: "img" });
  const grid = svg("g", { class: "grid" });
  for (let i = 0; i <= ticks; i++) {
    const v = (vmax / ticks) * i;
    const y = top + plotH - (v / vmax) * plotH;
    grid.append(svg("line", { x1: left, x2: width - right, y1: y, y2: y }));
    grid.append(svg("text", { x: left - 8, y: y + 4, "text-anchor": "end", "font-size": 11 }, format(v)));
  }
  root.append(grid);
  items.forEach((d, i) => {
    const x = left + band * i + (band - barW) / 2;
    const hgt = Math.max(2, (d.value / vmax) * plotH);
    const y = top + plotH - hgt;
    const g = svg("g", {});
    const rect = svg("rect", { class: "bar", x, y, width: barW, height: hgt, rx: 7, fill: d.color || "var(--accent)" });
    rect.append(svg("title", {}, d.title || `${d.label}: ${d.display ?? format(d.value)}`));
    g.append(rect);
    g.append(svg("text", { class: "val", x: x + barW / 2, y: y - 7, "text-anchor": "middle" }, d.display ?? format(d.value)));
    wrapLabel(d.label, Math.max(6, Math.floor(band / 7.2))).forEach((line, k) => {
      g.append(svg("text", { x: x + barW / 2, y: top + plotH + 18 + k * 14, "text-anchor": "middle" }, line));
    });
    root.append(g);
  });
  root.append(svg("line", { class: "axis", x1: left, x2: width - right, y1: top + plotH, y2: top + plotH }));
  return root;
}

/** Grouped bars. groups: [{label, values: [number]}], series: [{name, color}] */
export function groupedBarChart(groups, series, { max, ticks = 4, format = (v) => v, height = 260, width = 560 } = {}) {
  const top = 26, bottom = 52, left = 40, right = 8;
  const plotH = height - top - bottom, plotW = width - left - right;
  const vmax = max ?? niceMax(Math.max(...groups.flatMap((g) => g.values), 0));
  const band = plotW / groups.length;
  const inner = band * 0.74;
  const barW = Math.min(46, inner / series.length - 6);
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${width} ${height}`, role: "img" });
  const grid = svg("g", { class: "grid" });
  for (let i = 0; i <= ticks; i++) {
    const v = (vmax / ticks) * i;
    const y = top + plotH - (v / vmax) * plotH;
    grid.append(svg("line", { x1: left, x2: width - right, y1: y, y2: y }));
    grid.append(svg("text", { x: left - 8, y: y + 4, "text-anchor": "end", "font-size": 11 }, format(v)));
  }
  root.append(grid);
  groups.forEach((g, gi) => {
    const groupW = series.length * (barW + 6) - 6;
    const x0 = left + band * gi + (band - groupW) / 2;
    g.values.forEach((value, si) => {
      const x = x0 + si * (barW + 6);
      const hgt = Math.max(2, (value / vmax) * plotH);
      const y = top + plotH - hgt;
      const rect = svg("rect", { class: "bar", x, y, width: barW, height: hgt, rx: 6, fill: series[si].color });
      rect.append(svg("title", {}, `${series[si].name} · ${g.label}: ${format(value)}`));
      root.append(rect);
      root.append(svg("text", { class: "val", x: x + barW / 2, y: y - 6, "text-anchor": "middle", "font-size": 11 }, format(value)));
    });
    wrapLabel(g.label, Math.max(6, Math.floor(band / 7.2))).forEach((line, k) => {
      root.append(svg("text", { x: left + band * gi + band / 2, y: top + plotH + 18 + k * 14, "text-anchor": "middle" }, line));
    });
  });
  root.append(svg("line", { class: "axis", x1: left, x2: width - right, y1: top + plotH, y2: top + plotH }));
  return root;
}
