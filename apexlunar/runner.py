# Version: V26.281.0300
"""`apexlunar scheduler`: the background scheduler for places with no OS scheduler
to call - the Home Assistant add-on container.

A separate process from the web app. Once a minute it reads config.json, and if
the daily update is on, today's run hasn't happened and the clock has passed
schedule.apply_at (this machine's clock), it runs the same update as
`apexlunar update`. On start-up that also catches up a run missed while the
add-on was stopped. A failed run is retried every 15 minutes until it works.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from . import service as svc

RETRY = timedelta(minutes=15)


def due(now: datetime, cfg: dict, state: dict) -> bool:
    sch = cfg.get("schedule", {})
    if not sch.get("enabled", True):
        return False
    hh, mm = (int(x) for x in str(sch.get("apply_at", "00:05")).split(":"))
    if (now.hour, now.minute) < (hh, mm):
        return False
    if state.get("scheduled_date") == now.date().isoformat():
        return False  # already done today
    tried = state.get("scheduled_attempt_at")
    return not tried or now - datetime.fromisoformat(tried) >= RETRY


def main() -> None:
    print("ApexLunar scheduler running", flush=True)
    while True:
        now = datetime.now()
        try:
            if due(now, svc.load_config(), svc.read_state()):
                svc.write_state(scheduled_attempt_at=now.isoformat(timespec="seconds"))
                for line in svc.apply_and_record(svc.load_config(), "Scheduled"):
                    print(line, flush=True)
                svc.write_state(scheduled_date=now.date().isoformat(), scheduled_attempt_at=None)
        except Exception as e:  # logged by apply_and_record; retried after RETRY
            print(f"Scheduled update failed: {e}", flush=True)
        time.sleep(60 - datetime.now().second)
