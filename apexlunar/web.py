# Version: V26.281.0235
"""Local web app for configuration, preview and manual changes.

The daily update is NOT run here: it is `python -m apexlunar update`, started by
the operating system's scheduler (see schedule.py). This page installs/removes
that schedule and shows what it did, from the shared activity log.
"""
from __future__ import annotations

import json
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import schedule
from . import service as svc
from .apex import ApexError

STATIC = Path(__file__).resolve().parent / "static"


class App:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.lock = threading.Lock()  # one Apex conversation at a time from this page

    def cfg(self) -> dict:
        return svc.load_config(self.config_path)

    def preview(self, day: str | None) -> dict:
        cfg = self.cfg()
        with self.lock:
            return svc.public(svc.plan(cfg, svc.connect(cfg), day))

    def apply(self, day: str | None) -> list[str]:
        cfg = self.cfg()
        with self.lock:
            return svc.apply_and_record(cfg, "Manual", day)

    def restore(self, filename: str) -> list[str]:
        cfg = self.cfg()
        with self.lock:
            lines = svc.restore(svc.connect(cfg), filename)
        svc.log_activity("Manual", "MISMATCH" not in "".join(lines), f"Restored {filename}", lines)
        return lines

    def schedule_info(self) -> dict:
        return {**schedule.status(), "configured_at": self.cfg().get("schedule", {}).get("apply_at", "00:05"),
                "state": svc.read_state()}

    def schedule_action(self, body: dict) -> dict:
        action = body.get("action")
        if action == "install":
            at = str(body.get("at") or "00:05")
            msg = schedule.install(at)
            cfg = self.cfg()
            cfg.setdefault("schedule", {})["apply_at"] = at
            cfg["schedule"].pop("auto_apply", None)  # pre-scheduler setting
            svc.save_config(cfg, self.config_path)
        elif action == "uninstall":
            msg = schedule.uninstall()
        elif action == "run":
            msg = schedule.run_now()
        else:
            raise ValueError(f"unknown action {action!r}")
        svc.log_activity("Manual", True, f"Schedule: {msg}")
        return {"message": msg, **self.schedule_info()}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, code: int, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def _run(self, fn):
            try:
                self._send(200, fn())
            except (ApexError, svc.ConfigError, schedule.ScheduleError, ValueError, KeyError) as e:
                self._send(400, {"error": str(e)})
            except Exception as e:
                traceback.print_exc()
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            routes = {
                "/api/config": lambda: config_out(app.cfg()),
                "/api/preview": lambda: app.preview(q.get("date") or None),
                "/api/outputs": lambda: light_outputs(app),
                "/api/backups": svc.list_backups,
                "/api/status": lambda: {"activity": svc.read_activity(), "state": svc.read_state()},
                "/api/schedule": app.schedule_info,
            }
            if url.path in routes:
                return self._run(routes[url.path])
            self._send(404, {"error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            body = self._body()
            routes = {
                "/api/config": lambda: save_config(app, body),
                "/api/apply": lambda: {"log": app.apply(body.get("date") or None)},
                "/api/restore": lambda: {"log": app.restore(body["file"])},
                "/api/schedule": lambda: app.schedule_action(body),
            }
            if path in routes:
                return self._run(routes[path])
            self._send(404, {"error": "not found"})

    return Handler


def config_out(cfg: dict) -> dict:
    out = json.loads(json.dumps(cfg))
    out["apex"]["has_password"] = bool(out["apex"].get("password"))
    out["apex"]["password"] = ""
    return out


def save_config(app: App, incoming: dict) -> dict:
    cfg = app.cfg()
    loc = incoming.get("location", {})
    lat, lon = float(loc["latitude"]), float(loc["longitude"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("latitude must be -90..90 and longitude -180..180")
    cfg["location"] = {"latitude": lat, "longitude": lon}
    a = incoming.get("apex", {})
    for k in ("host", "username", "lunar_did"):
        if a.get(k):
            cfg["apex"][k] = str(a[k]).strip()
    if a.get("password"):
        cfg["apex"]["password"] = a["password"]
    t = incoming.get("table", {})
    cfg["table"] = {
        "max_intensity": max(0, min(100, int(t.get("max_intensity", 15)))),
        "ramp_altitude_deg": max(0.5, min(90.0, float(t.get("ramp_altitude_deg", 10)))),
        "channels": {k: max(0, min(100, int(v))) for k, v in (t.get("channels") or {}).items()} or None,
        "max_rows": max(3, min(24, int(t.get("max_rows", 12)))),
    }
    svc.save_config(cfg, app.config_path)
    svc.log_activity("Manual", True, "Settings saved")
    return config_out(cfg)


def light_outputs(app: App) -> list[dict]:
    cfg = app.cfg()
    with app.lock:
        return svc.light_outputs(svc.connect(cfg))


def serve(config_path: Path, bind: str = "127.0.0.1", port: int = 8788, open_browser: bool = True) -> None:
    app = App(config_path)
    # No address reuse: on Windows it lets a second copy share the port silently.
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        httpd = ThreadingHTTPServer((bind, port), make_handler(app))
    except OSError:
        raise SystemExit(f"Port {port} is already in use - ApexLunar is probably already running. "
                         f"Open http://127.0.0.1:{port}/ or start with --port <other>.")
    url = f"http://{'127.0.0.1' if bind in ('0.0.0.0', '') else bind}:{port}/"
    print(f"ApexLunar running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
