// Number, time and label formatting shared by every view.

const intFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function fmtNum(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  if (Number.isInteger(value)) return intFmt.format(value);
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 4 : 6;
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits }).format(value);
}

export function fmtValue(value) {
  if (typeof value === "number") return fmtNum(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(fmtValue).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return value === null || value === undefined ? "—" : String(value);
}

export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  if (seconds < 0.1) return "<0.1 s";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m} min ${String(s).padStart(2, "0")} s`;
}

export function fmtCost(usd) {
  if (!usd) return "$0";
  if (usd < 0.0001) return "<$0.0001";
  return `$${usd.toFixed(usd < 0.1 ? 4 : 2)}`;
}

export const fmtInt = (n) => intFmt.format(n || 0);
export const fmtPct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`;

export function relTime(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  const diff = (Date.now() - then.getTime()) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  if (diff < 172800) return "yesterday";
  return then.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) + ", " +
    then.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function fullDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: false });
}

/** One label/icon/explanation per observation kind, used by every view. */
export const KINDS = {
  ok: { label: "Passed", icon: "check", explain: "The program ran, produced RESULT and every self-check passed." },
  runtime: { label: "Runtime error", icon: "zap", explain: "The program crashed while running. The traceback below shows the failing line." },
  assertion: { label: "Self-check failed", icon: "alert", explain: "Two quantities that the program computed in different ways disagreed, so an assert caught a logic bug." },
  syntax: { label: "Syntax error", icon: "code", explain: "The program could not be parsed, so it never ran." },
  timeout: { label: "Timed out", icon: "clock", explain: "The program ran past the time limit and the sandbox killed it." },
  contract: { label: "Contract broken", icon: "info", explain: "The program did not return a valid RESULT dict, or it had fewer than two self-checks." },
  blocked: { label: "Blocked by safety gate", icon: "shield", explain: "The safety gate rejected the code before it ran (a forbidden import, name or attribute)." },
  stopped: { label: "Stopped", icon: "stop", explain: "The run was stopped by the user." },
};

export const kindOf = (k) => KINDS[k] || { label: k, icon: "info", explain: "" };

export const INJECT_LABELS = { crash: "Crash bug", logic: "Logic bug" };

export function errorHeadline(obs) {
  if (!obs) return "";
  if (obs.ok) return `${obs.asserts} self-check${obs.asserts === 1 ? "" : "s"} passed`;
  const tb = (obs.traceback || "").trim().split("\n").filter(Boolean);
  const last = tb.length ? tb[tb.length - 1].trim() : "";
  const msgLines = (obs.message || "").split("\n").map((s) => s.trim()).filter(Boolean);
  let text = last && /Error|Exception|Interrupt/.test(last) ? last : msgLines.find((l) => !/^Code rejected/.test(l)) || msgLines[0] || obs.kind;
  text = text.replace(/^-\s*/, "");
  if (obs.line && !/line \d+/.test(text)) text = `line ${obs.line} · ${text}`;
  return text;
}
