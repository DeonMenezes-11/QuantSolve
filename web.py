"""Start the QuantSolve website.

    python3 web.py                  # serves http://127.0.0.1:8503 and opens the browser
    python3 web.py --port 9000 --no-browser
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="QuantSolve web UI")
    parser.add_argument("--port", type=int, default=8503)
    parser.add_argument("--host", default="127.0.0.1", help="keep the default: local use only")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print(f"QuantSolve is running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    uvicorn.run("webapp.server:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
