"""Capture screenshots of the QuantSolve website with headless Chrome over the DevTools protocol.

    python3 web.py --port 8611 --no-browser &
    python3 report/capture_ui.py --base http://127.0.0.1:8611 --run <showcase run id> [--live]

Writes report/figures/ui_*.png (light theme, clipped to the interesting part of each page).
--live solves one sample problem through the Solve page, so it makes real API calls (~US$0.005).
"""

from __future__ import annotations

import argparse
import base64
import itertools
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from websocket import create_connection

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FIGURES = Path(__file__).resolve().parent / "figures"

# Union of several elements' boxes in page coordinates, with padding, optionally height-capped.
BOX_JS = """
window.__box = (selectors, pad = 18, maxH = 100000) => {
  const els = selectors.map((s) => document.querySelector(s)).filter(Boolean);
  if (!els.length) return null;
  const rs = els.map((e) => e.getBoundingClientRect());
  const left = Math.min(...rs.map((r) => r.left)), top = Math.min(...rs.map((r) => r.top));
  const right = Math.max(...rs.map((r) => r.right)), bottom = Math.max(...rs.map((r) => r.bottom));
  return [Math.max(0, left - pad + scrollX), Math.max(0, top - pad + scrollY),
          right - left + 2 * pad, Math.min(bottom - top + 2 * pad, maxH)];
};
"""


class Page:
    """Minimal Chrome DevTools Protocol client for one tab."""

    def __init__(self, ws_url: str) -> None:
        self.ws = create_connection(ws_url, timeout=60, suppress_origin=True)
        self.ids = itertools.count(1)

    def send(self, method: str, **params):
        msg_id = next(self.ids)
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("id") == msg_id:
                return reply.get("result", {})

    def js(self, expression: str):
        result = self.send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        return result.get("result", {}).get("value")

    def wait_for(self, expression: str, timeout: float = 30) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.js(f"!!({expression})"):  # DOM nodes do not serialise, so coerce to bool
                return True
            time.sleep(0.4)
        return False

    def viewport(self, width: int, height: int = 1000, mobile: bool = False) -> None:
        self.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                  deviceScaleFactor=2 if mobile else 1, mobile=mobile)

    def goto(self, url: str, ready: str, settle: float = 1.2) -> None:
        self.send("Page.navigate", url=url)
        if not self.wait_for(ready, timeout=40):
            raise RuntimeError(f"page did not become ready: {url}")
        time.sleep(settle)
        self.js(BOX_JS)

    def shot(self, out: Path, selectors: list[str], max_height: int = 100000, scale: float = 1.0) -> None:
        box = self.js(f"window.__box({json.dumps(selectors)}, 18, {max_height})")
        if not box:
            raise RuntimeError(f"nothing to capture for {selectors}")
        x, y, w, h = box
        data = self.send("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                         clip={"x": x, "y": y, "width": w, "height": h, "scale": scale})["data"]
        out.write_bytes(base64.b64decode(data))
        print(f"saved {out.name} ({int(w * scale)}x{int(h * scale)})")


def open_chrome(port: int, profile: str) -> subprocess.Popen:
    return subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}",
                             f"--user-data-dir={profile}", "--hide-scrollbars",
                             "--window-size=1440,1000", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def page_ws_url(port: int, timeout: float = 20) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json") as resp:
                targets = json.load(resp)
            return next(t for t in targets if t.get("type") == "page")["webSocketDebuggerUrl"]
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Chrome did not expose a debuggable page")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8611")
    parser.add_argument("--run", default="20261004-235610_sip_stepup_inject-logic", help="showcase run id")
    parser.add_argument("--live", action="store_true", help="also solve one problem through the UI")
    parser.add_argument("--port", type=int, default=9333)
    args = parser.parse_args()
    FIGURES.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="qs-chrome-")
    chrome = open_chrome(args.port, profile)
    try:
        page = Page(page_ws_url(args.port))
        page.send("Page.enable")
        page.viewport(1440)
        # Light theme for print, intro banner hidden, no remembered run.
        page.goto(args.base + "/#/how", "document.querySelector('.diagram')")
        page.js("localStorage.setItem('qs-theme','light'); localStorage.setItem('qs-hero-hidden','true');"
                "localStorage.setItem('qs-opts', JSON.stringify({inject:'crash', attempts:5}));"
                "sessionStorage.clear(); true")
        page.send("Page.reload", ignoreCache=True)
        time.sleep(1)
        page.wait_for("document.documentElement.dataset.theme === 'light' && document.querySelector('.diagram')")
        time.sleep(1)
        page.js(BOX_JS)
        page.shot(FIGURES / "ui_how.png", [".how-hero", ".diagram-card"])
        page.shot(FIGURES / "ui_diagram.png", [".diagram-card"], scale=2)  # print-quality loop diagram

        page.goto(f"{args.base}/#/run/{args.run}", "document.querySelector('.final')")
        page.js("(() => { const a = document.querySelectorAll('.attempt')[0]; a.querySelector('.attempt-head').click();"
                "[...a.querySelectorAll('.tabs button')].find((b) => b.textContent.startsWith('Code')).click(); })()")
        time.sleep(0.8)
        page.js(BOX_JS)
        page.shot(FIGURES / "ui_replay.png", [".crumbs", ".replay-grid"], max_height=1500)
        page.shot(FIGURES / "ui_attempt.png", [".attempt"], max_height=1100)

        page.goto(args.base + "/#/results", "document.querySelector('.heat')")
        page.shot(FIGURES / "ui_results.png", [".page-head", ".kpis", ".grid-3"])

        page.goto(args.base + "/#/history?scope=all", "document.querySelectorAll('a.run-row').length > 0")
        page.shot(FIGURES / "ui_history.png", [".page-head", "main .card"], max_height=900)

        if args.live:
            page.goto(args.base + "/#/solve", "document.querySelector('.example')")
            page.js("[...document.querySelectorAll('.example')].find((b) => b.textContent.includes('Income tax')).click();"
                    "document.querySelector('.composer-foot .btn').click(); true")
            if not page.wait_for("document.querySelector('.final')", timeout=180):
                raise RuntimeError("the live run did not finish")
            time.sleep(2)
            page.js("document.getElementById('toasts').replaceChildren(); window.scrollTo(0, 0); true")
            time.sleep(0.6)
            page.js(BOX_JS)
            page.shot(FIGURES / "ui_solve.png", [".solve-grid"], max_height=1350)

            page.viewport(390, 844, mobile=True)
            page.goto(f"{args.base}/#/solve", "document.querySelector('.final')")
            page.shot(FIGURES / "ui_mobile.png", [".final"], max_height=1100, scale=1.0)
    finally:
        chrome.terminate()
        chrome.wait(10)
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
