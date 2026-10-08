# Version: V26.281.0234
"""Install the daily `apexlunar update` run with the operating system's scheduler.

Windows: a Task Scheduler task with two triggers - every day at the chosen time
(computer clock) and one minute after logon, so a day missed while the PC was
off or asleep is caught up. "Run as soon as possible after a missed start" is
on too. The task runs pythonw.exe, so no console window flashes.

macOS (launchd) and Raspberry Pi (systemd timer) are planned; the `update`
command they will run is the same.
"""
from __future__ import annotations

import csv
import io
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from .service import ROOT

TASK_NAME = "ApexLunar Daily Update"


class ScheduleError(RuntimeError):
    pass


def _windows_python() -> str:
    """pythonw.exe beside the interpreter running us (no console window)."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _task_xml(at: str, user: str) -> str:
    hh, mm = (int(x) for x in at.split(":"))
    start = (datetime.now() + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Writes today's moon-matched lunar table to the Apex. Installed by ApexLunar ({escape(str(ROOT))}).</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start.strftime('%Y-%m-%dT%H:%M:%S')}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
      <Delay>PT1M</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(_windows_python())}</Command>
      <Arguments>-m apexlunar update --scheduled</Arguments>
      <WorkingDirectory>{escape(str(ROOT))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _require_windows() -> None:
    if sys.platform != "win32":
        raise ScheduleError("Scheduling is Windows-only so far; macOS and Raspberry Pi are next. "
                            "Meanwhile, run `python -m apexlunar update` from cron or launchd.")


def install(at: str = "00:05") -> str:
    _require_windows()
    datetime.strptime(at, "%H:%M")  # validates
    user = _run(["whoami"]).stdout.strip()
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
        f.write(_task_xml(at, user))
        xml_path = f.name
    try:
        r = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", xml_path, "/F"])
    finally:
        Path(xml_path).unlink(missing_ok=True)
    if r.returncode:
        raise ScheduleError((r.stderr or r.stdout).strip())
    return f"Installed '{TASK_NAME}': daily at {at} and 1 minute after logon."


def uninstall() -> str:
    _require_windows()
    r = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if r.returncode:
        if "cannot find" in (r.stderr + r.stdout).lower():
            return "Not installed."
        raise ScheduleError((r.stderr or r.stdout).strip())
    return f"Removed '{TASK_NAME}'."


def run_now() -> str:
    _require_windows()
    r = _run(["schtasks", "/Run", "/TN", TASK_NAME])
    if r.returncode:
        raise ScheduleError((r.stderr or r.stdout).strip())
    return "Started the scheduled task."


def status() -> dict:
    """{"supported", "installed", "at", "next_run", "last_run", "last_result"}."""
    if sys.platform != "win32":
        return {"supported": False, "installed": False}
    r = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "CSV"])
    if r.returncode:
        return {"supported": True, "installed": False}
    rows = list(csv.DictReader(io.StringIO(r.stdout)))
    info = {"supported": True, "installed": True, "at": None,
            "next_run": None, "last_run": None, "last_result": None}
    for row in rows:  # one row per trigger
        info["next_run"] = info["next_run"] or row.get("Next Run Time")
        info["last_run"] = row.get("Last Run Time") or info["last_run"]
        info["last_result"] = row.get("Last Result") or info["last_result"]
        start = row.get("Start Time", "")
        if row.get("Schedule Type", "").strip().lower() == "daily" and start:
            try:
                info["at"] = datetime.strptime(start.strip(), "%I:%M:%S %p").strftime("%H:%M")
            except ValueError:
                info["at"] = start.strip()
    if info["last_run"] and info["last_run"].startswith("11/30/1999"):
        info["last_run"] = None  # Task Scheduler's "never ran"
    return info
