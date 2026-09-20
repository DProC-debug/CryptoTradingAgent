"""Local dashboard server: serves web/meeting-room.html and a live /api/state endpoint.

    python web/server.py [--port 8765] [--interval-minutes 5] [--autostart] [--open]

A background thread pulls a fresh snapshot of the live account (balance, positions, recent
verdicts - see export_state.collect_state) every --interval-minutes while the refresh loop is
enabled, and immediately whenever it's switched on. The dashboard's Start/Stop button toggles
that loop through /api/loop. It only controls the dashboard's data refresh - it never starts,
stops, or touches the trading bot process, and nothing here places orders.

Binds to 127.0.0.1 only and rejects requests with a non-local Host header (DNS-rebinding
guard), since /api/state exposes live account data. Standard library only.
"""

import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(WEB_DIR))

import export_state  # noqa: E402  (also loads .env and puts the project root on sys.path)

STATIC_ROUTES = {
    "/": (WEB_DIR / "meeting-room.html", "text/html; charset=utf-8"),
}
STATIC_DIRS = {
    "/models/": (WEB_DIR / "models", {".js": "application/javascript; charset=utf-8"}),
    "/audio/": (WEB_DIR / "audio", {".mp3": "audio/mpeg"}),
}
LOCAL_HOSTS = {"localhost", "127.0.0.1"}


class RefreshLoop:
    """Owns the latest snapshot and the enable/disable state of the periodic refresh."""

    def __init__(self, interval_seconds: float, collector, enabled: bool = False):
        self.interval_seconds = interval_seconds
        self.collector = collector  # () -> dict; raises on failure
        self.enabled = enabled
        self.state = None
        self.last_refreshed_at = None
        self.last_error = None
        self.refreshing = False
        self._wake = threading.Event()
        self._lock = threading.Lock()

    def set_enabled(self, enabled: bool):
        with self._lock:
            was_enabled = self.enabled
            self.enabled = enabled
        if enabled and not was_enabled:
            self._wake.set()  # capture fresh data right away, then settle into the interval

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self.enabled,
                "intervalMinutes": self.interval_seconds / 60,
                "lastRefreshedAt": self.last_refreshed_at,
                "lastError": self.last_error,
                "refreshing": self.refreshing,
            }

    def _refresh(self):
        with self._lock:
            self.refreshing = True
        try:
            snapshot = self.collector()
            with self._lock:
                self.state = snapshot
                self.last_refreshed_at = datetime.now().isoformat(timespec="seconds")
                self.last_error = None
            print(f"[refresh] ok - balance ${snapshot.get('accountBalance', 0):,.2f}, "
                  f"{len(snapshot.get('positions', []))} open position(s)")
        except Exception as e:  # keep serving the last good snapshot
            with self._lock:
                self.last_error = str(e)
            print(f"[refresh] FAILED: {e}")
        finally:
            with self._lock:
                self.refreshing = False

    def run(self):
        self._refresh()  # one snapshot at boot so the dashboard isn't empty before Start
        next_due = time.monotonic() + self.interval_seconds
        while True:
            triggered = self._wake.wait(timeout=max(0.0, next_due - time.monotonic()))
            self._wake.clear()
            if triggered or self.enabled:
                if triggered or time.monotonic() >= next_due:
                    self._refresh()
                    next_due = time.monotonic() + self.interval_seconds
            elif time.monotonic() >= next_due:
                next_due = time.monotonic() + self.interval_seconds


def make_live_collector():
    """Collector backed by the real account; the trader client is built once and reused."""
    trader_holder = {}

    def collect():
        if "trader" not in trader_holder:
            trader_holder["trader"] = export_state.build_trader()
        return export_state.collect_state(trader_holder["trader"])

    return collect


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # Browsers routinely abort audio/model range requests mid-response; that's not an error
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def make_handler(loop: RefreshLoop):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep the console for refresh messages

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in LOCAL_HOSTS

        def _send(self, status: int, body: bytes, content_type: str, extra: dict = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload):
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

        def _serve_file(self, path: Path, content_type: str):
            if not path.is_file():
                self._json(404, {"error": "not found"})
                return
            data = path.read_bytes()
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                start_s, _, end_s = rng[6:].partition("-")
                try:
                    start = int(start_s) if start_s else 0
                    end = int(end_s) if end_s else len(data) - 1
                except ValueError:
                    start, end = 0, len(data) - 1
                end = min(end, len(data) - 1)
                if start <= end:
                    self._send(206, data[start:end + 1], content_type, {
                        "Content-Range": f"bytes {start}-{end}/{len(data)}",
                        "Accept-Ranges": "bytes",
                    })
                    return
            self._send(200, data, content_type, {"Accept-Ranges": "bytes"})

        def do_GET(self):
            if not self._host_ok():
                self._json(403, {"error": "forbidden host"})
                return
            path = self.path.split("?", 1)[0]

            if path in STATIC_ROUTES:
                file_path, ctype = STATIC_ROUTES[path]
                self._serve_file(file_path, ctype)
            elif path == "/api/state":
                state = loop.state
                if state is None:
                    self._json(503, {"error": "no snapshot yet", **loop.status()})
                else:
                    self._json(200, state)
            elif path == "/api/loop":
                self._json(200, loop.status())
            else:
                for prefix, (directory, allowed) in STATIC_DIRS.items():
                    if path.startswith(prefix):
                        name = os.path.basename(path[len(prefix):])
                        ext = os.path.splitext(name)[1].lower()
                        if name and ext in allowed:
                            self._serve_file(directory / name, allowed[ext])
                            return
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok():
                self._json(403, {"error": "forbidden host"})
                return
            if self.path.split("?", 1)[0] != "/api/loop":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                enabled = body["enabled"]
                if not isinstance(enabled, bool):
                    raise ValueError("enabled must be a boolean")
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                self._json(400, {"error": f"bad request: {e}"})
                return
            loop.set_enabled(enabled)
            self._json(200, loop.status())

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=int(os.getenv("DASHBOARD_PORT", "8765")))
    parser.add_argument("--interval-minutes", type=float,
                        default=float(os.getenv("DASHBOARD_REFRESH_MINUTES", "5")),
                        help="How often to refresh the snapshot while the loop is enabled (default 5)")
    parser.add_argument("--autostart", action="store_true",
                        help="Start with the refresh loop already enabled instead of waiting for the Start button")
    parser.add_argument("--open", action="store_true", help="Open the dashboard in your browser")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    if not (WEB_DIR / "models" / "room.js").is_file():
        print("Note: no 3D models found in web/models/ - the page will show a message instead of the scene. "
              "They aren't distributed with the repo; see the README's \"3D assets\" section. "
              "(/api/state still works.)")

    loop = RefreshLoop(args.interval_minutes * 60, make_live_collector(), enabled=args.autostart)
    threading.Thread(target=loop.run, daemon=True, name="refresh-loop").start()

    server = QuietServer(("127.0.0.1", args.port), make_handler(loop))
    url = f"http://localhost:{args.port}/"
    print(f"Dashboard: {url}  (refresh every {args.interval_minutes:g} min while enabled; "
          f"loop {'ON' if args.autostart else 'OFF - press Start on the page'})")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
