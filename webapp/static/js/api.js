// JSON API and Server-Sent Events helpers.

export const OFFLINE_MESSAGE = "Can't reach the QuantSolve server. Start it with python3 web.py (in the project folder), then try again.";

/** Tell the app shell whether the server answered (it updates the status pill). */
function signal(online) {
  window.dispatchEvent(new CustomEvent(online ? "qs:online" : "qs:offline"));
}

export async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    // fetch only rejects when no HTTP response arrived at all: the server is not running.
    signal(false);
    const err = new Error(OFFLINE_MESSAGE);
    err.offline = true;
    throw err;
  }
  signal(true);
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const detail = data && data.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ")
      : `${res.status} ${res.statusText}`;
    const err = new Error(message);
    err.status = res.status;
    throw err;
  }
  return data;
}

const EVENTS = ["started", "attempt_start", "action", "observation", "reflection", "summarizing", "final", "error"];

/** Follow a solve job. handlers: {event(kind, data), end(), lost(err)}. Returns {close()}. */
export function followRun(jobId, handlers) {
  const source = new EventSource(`/api/runs/${encodeURIComponent(jobId)}/events`);
  let finished = false;
  for (const kind of EVENTS) {
    source.addEventListener(kind, (e) => {
      let data = {};
      try { data = JSON.parse(e.data); } catch { /* ignore */ }
      handlers.event(kind, data);
    });
  }
  source.addEventListener("end", () => {
    finished = true;
    source.close();
    handlers.end?.();
  });
  source.onerror = async () => {
    if (finished) return;
    // EventSource reconnects by itself; only give up when the job no longer exists.
    if (source.readyState === EventSource.CLOSED) {
      handlers.lost?.(new Error("Lost the connection to the server."));
      return;
    }
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(jobId)}`);
      if (res.status === 404) {
        source.close();
        handlers.lost?.(new Error("This run is no longer on the server (it may have restarted)."));
      }
    } catch { /* server down; EventSource keeps retrying */ }
  };
  return { close: () => { finished = true; source.close(); } };
}
