// Line diff (longest common subsequence) used for "what changed since the last attempt".

export function diffLines(before, after) {
  const a = before.replace(/\n$/, "").split("\n");
  const b = after.replace(/\n$/, "").split("\n");
  const n = a.length, m = b.length;
  const lcs = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const ops = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { ops.push({ t: "=", text: b[j], bi: j + 1 }); i++; j++; }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) { ops.push({ t: "-", text: a[i], ai: i + 1 }); i++; }
    else { ops.push({ t: "+", text: b[j], bi: j + 1 }); j++; }
  }
  while (i < n) { ops.push({ t: "-", text: a[i], ai: i + 1 }); i++; }
  while (j < m) { ops.push({ t: "+", text: b[j], bi: j + 1 }); j++; }
  return ops;
}

/** Keep `context` unchanged lines around each change; the rest becomes {t: "gap", count}. */
export function withContext(ops, context = 3) {
  const keep = new Array(ops.length).fill(false);
  ops.forEach((op, idx) => {
    if (op.t !== "=") for (let k = Math.max(0, idx - context); k <= Math.min(ops.length - 1, idx + context); k++) keep[k] = true;
  });
  const out = [];
  let gap = 0;
  ops.forEach((op, idx) => {
    if (keep[idx]) {
      if (gap) out.push({ t: "gap", count: gap });
      gap = 0;
      out.push(op);
    } else gap++;
  });
  if (gap) out.push({ t: "gap", count: gap });
  return out;
}

export const changeCount = (ops) => ops.filter((o) => o.t !== "=").length;
