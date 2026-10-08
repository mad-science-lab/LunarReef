# Version: V26.281.0145
"""Local web app: standard-library HTTP server + a daily auto-apply loop."""
from __future__ import annotations

import json
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import service as svc
from .apex import ApexError

STATIC = Path(__file__).resolve().parent / "static"
STATE_FILE = svc.ROOT / "state.json"


class App:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.lock = threading.Lock()          # one Apex conversation at a time
        self.activity: list[dict] = []
        self.state = self._load_state()

    # -- persistence
    def cfg(self) -> dict:
        return svc.load_config(self.config_path)

    def _load_state(self) -> dict:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        STATE_FILE.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def note(self, msg: str, lines: list[str] | None = None) -> None:
        self.activity.insert(0, {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 "msg": msg, "lines": lines or []})
        del self.activity[50:]

    # -- actions
    def preview(self, day: str | None) -> dict:
        cfg = self.cfg()
        with self.lock:
            return svc.public(svc.plan(cfg, svc.connect(cfg), day))

    def apply(self, day: str | None, why: str) -> list[str]:
        cfg = self.cfg()
        with self.lock:
            apex = svc.connect(cfg)
            p = svc.plan(cfg, apex, day)
            lines = svc.apply(cfg, apex, p)
        self.state["last_applied"] = p["moon"]["date"]
        self.state["last_applied_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state()
        self.note(f"{why}: applied table for {p['moon']['date']} "
                  f"({p['moon']['phase']}, {p['moon']['illumination'] * 100:.0f}% lit)", lines)
        return lines

    # -- scheduler
    def scheduler(self) -> None:
        """Once per controller day, at schedule.apply_at controller time, write the table."""
        offset_h = None
        while True:
            try:
                cfg = self.cfg()
                sch = cfg.get("schedule", {})
                if sch.get("auto_apply"):
                    if offset_h is None:
                        with self.lock:
                            offset_h = svc.connect(cfg).utc_offset_hours()
                    now = datetime.now(timezone.utc) + timedelta(hours=offset_h)
                    hh, mm = (int(x) for x in str(sch.get("apply_at", "00:05")).split(":"))
                    due = now.hour * 60 + now.minute >= hh * 60 + mm
                    if due and self.state.get("last_applied") != now.date().isoformat():
                        self.apply(None, "Scheduled")
                        offset_h = None   # re-read daily in case the Apex changed DST
            except Exception as e:  # keep the loop alive; show the problem in the UI
                self.note(f"Scheduled apply failed: {e}")
                time.sleep(240)
            time.sleep(60)


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
            except (ApexError, svc.ConfigError, ValueError, KeyError) as e:
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
                "/api/status": lambda: {"activity": app.activity, "state": app.state},
            }
            if url.path in routes:
                return self._run(routes[url.path])
            self._send(404, {"error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/config":
                return self._run(lambda: save_config(app, self._body()))
            if path == "/api/apply":
                return self._run(lambda: {"log": app.apply(self._body().get("date") or None, "Manual")})
            if path == "/api/restore":
                def do():
                    cfg = app.cfg()
                    with app.lock:
                        lines = svc.restore(svc.connect(cfg), self._body()["file"])
                    app.note("Restored backup", lines)
                    return {"log": lines}
                return self._run(do)
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
    s = incoming.get("schedule", {})
    at = str(s.get("apply_at", "00:05"))
    hh, mm = (int(x) for x in at.split(":"))
    cfg["schedule"] = {"auto_apply": bool(s.get("auto_apply")), "apply_at": f"{hh:02d}:{mm:02d}"}
    svc.save_config(cfg, app.config_path)
    app.note("Settings saved")
    return config_out(cfg)


def light_outputs(app: App) -> list[dict]:
    cfg = app.cfg()
    with app.lock:
        return svc.light_outputs(svc.connect(cfg))


def serve(config_path: Path, bind: str = "127.0.0.1", port: int = 8788, open_browser: bool = True) -> None:
    app = App(config_path)
    threading.Thread(target=app.scheduler, daemon=True).start()
    httpd = ThreadingHTTPServer((bind, port), make_handler(app))
    url = f"http://{'127.0.0.1' if bind in ('0.0.0.0', '') else bind}:{port}/"
    print(f"ApexLunar running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
