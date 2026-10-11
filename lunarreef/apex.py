# Version: V26.281.0130
"""Minimal Neptune Apex local REST client (standard library only).

Writes use the same call as the Apex's own web UI: GET the output's full
config from /rest/config/oconf/<id>, change `prog`, and PUT the whole object back.
"""
from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.request
from typing import Any


class ApexError(RuntimeError):
    pass


class Apex:
    def __init__(self, host: str, username: str, password: str, timeout: float = 15):
        self.host = host.rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host
        self._user, self._pw, self._timeout = username, password, timeout
        self._http = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._logged_in = False

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.host + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with self._http.open(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise ApexError(f"{method} {path}: HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise ApexError(f"cannot reach {self.host}: {e.reason}") from None
        return json.loads(raw) if raw.strip() else None

    def login(self) -> None:
        try:
            self._call("POST", "/rest/login", {"login": self._user, "password": self._pw})
        except ApexError as e:
            raise ApexError(f"login failed ({e}) - check username/password in config.json") from None
        self._logged_in = True

    def _authed(self, method: str, path: str, body: Any = None) -> Any:
        if not self._logged_in:
            self.login()
        return self._call(method, path, body)

    def utc_offset_hours(self) -> float:
        """Controller's own timezone; its tables run on this clock, not the PC's."""
        st = self._call("GET", "/cgi-bin/status.json")
        return float(st.get("istat", st)["timezone"])

    def outputs(self) -> list[dict]:
        cfg = self._authed("GET", "/rest/config")
        return cfg["oconf"]  # never keep the rest: nconf holds the admin password

    def get_output(self, did: str) -> dict:
        return self._authed("GET", f"/rest/config/oconf/{did}")

    def put_output(self, obj: dict) -> Any:
        return self._authed("PUT", f"/rest/config/oconf/{obj['did']}", obj)

    def group_members(self, did: str) -> list[dict]:
        """The output plus every peer in the same group (same gid, gid != 0)."""
        outs = self.outputs()
        me = next((o for o in outs if o["did"] == did), None)
        if me is None:
            raise ApexError(f"no output with device ID {did}")
        gid = str(me.get("gid", "0"))
        if gid in ("", "0"):
            return [me]
        peers = [o for o in outs if str(o.get("gid")) == gid and o["did"] != did]
        return [me] + peers
