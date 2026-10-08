# Version: V26.281.0234
"""ApexLunar command line.

    python -m apexlunar web               local web app (default http://127.0.0.1:8788)
    python -m apexlunar moon              moon phase, rise/set for your location
    python -m apexlunar preview           current vs proposed Apex table (no changes)
    python -m apexlunar apply --write     back up, then write today's table
    python -m apexlunar restore FILE --write
    python -m apexlunar update            what the daily scheduled task runs
    python -m apexlunar schedule install [--at HH:MM] | uninstall | status | run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import service as svc
from .apex import Apex, ApexError
from .table import build_rows


def print_moon(m: dict) -> None:
    print(f"Location   {m['latitude']:.4f}, {m['longitude']:.4f}   "
          f"controller clock UTC{m['utc_offset']:+g}   {m['date']}")
    print(f"Phase      {m['phase']}, {m['illumination'] * 100:.0f}% lit, "
          f"age {m['age_days']} d ({'waxing' if m['waxing'] else 'waning'})")
    print(f"Moonrise   {', '.join(m['rises']) or 'none today'}")
    print(f"Moonset    {', '.join(m['sets']) or 'none today'}")
    print(f"Highest    {m['peak_altitude']:.0f} deg at {m['peak_time']}")


def print_rows(title: str, rows: list[dict]) -> None:
    print(f"\n{title}\n  time   master  channels")
    for r in rows:
        ch = ",".join(f"{k} {v}" for k, v in r["channels"].items())
        print(f"  {r['time']}  {r['intensity']:5d}%  {ch}")


def cmd_moon(cfg: dict, args) -> None:
    offset_h = args.utc_offset
    if offset_h is None:
        try:
            offset_h = Apex(cfg["apex"]["host"], "", "").utc_offset_hours()
        except (ApexError, KeyError):
            offset_h = datetime.now().astimezone().utcoffset().total_seconds() / 3600
    settings = svc.settings_from(cfg)
    info, samples = svc.moon_summary(cfg, offset_h, svc.controller_day(offset_h, args.date), settings)
    print_moon(info)
    print_rows("Master intensity curve:", svc.row_dicts(build_rows(samples, (), settings), []))


def cmd_apply(cfg: dict, args) -> None:
    apex = svc.connect(cfg)
    p = svc.plan(cfg, apex, args.date)
    print_moon(p["moon"])
    print("\nTarget     " + ", ".join(f"{m['name']} ({m['did']})" for m in p["members"]))
    print_rows("Current table:", p["current"])
    print_rows(f"Proposed table ({len(p['proposed'])} rows):", p["proposed"])
    if not args.write:
        print("\nPreview only. Re-run with: apply --write")
        return
    print()
    lines = svc.apply(cfg, apex, p)
    print("\n".join(lines))
    svc.write_state(last_applied=p["moon"]["date"])
    svc.log_activity("Command line", True, f"Command line: applied table for {p['moon']['date']}", lines)


def cmd_update(cfg: dict, args) -> None:
    """The scheduled job: write today's table if it changed, log the result, exit."""
    try:
        print("\n".join(svc.apply_and_record(cfg, "Scheduled" if args.scheduled else "Update")))
    except Exception as e:  # already logged; the non-zero exit shows in Task Scheduler
        sys.exit(f"Update failed: {e}")


def cmd_schedule(cfg: dict, args) -> None:
    from . import schedule
    if args.action == "install":
        at = args.at or cfg.get("schedule", {}).get("apply_at", "00:05")
        print(schedule.install(at))
        cfg.setdefault("schedule", {})["apply_at"] = at
        svc.save_config(cfg, args.config)
    elif args.action == "uninstall":
        print(schedule.uninstall())
    elif args.action == "run":
        print(schedule.run_now())
    else:
        st = schedule.status()
        if not st.get("installed"):
            print("Not installed." if st.get("supported") else "Not supported on this system yet.")
        else:
            print(f"Installed: daily at {st['at']} (and 1 minute after logon)")
            print(f"Next run:  {st['next_run']}")
            print(f"Last run:  {st['last_run'] or 'never'}   result: {st['last_result']}")


def cmd_restore(cfg: dict, args) -> None:
    name = Path(args.file).name
    obj = json.loads((svc.BACKUP_DIR / name).read_text(encoding="utf-8"))
    print(f"Restore {obj['name']} ({obj['did']}) program:\n{obj['prog']}")
    if not args.write:
        print("\nPreview only. Re-run with --write to restore.")
        return
    print("\n".join(svc.restore(svc.connect(cfg), name)))


def cmd_web(cfg: dict, args) -> None:
    from .web import serve
    serve(args.config, args.bind, args.port, open_browser=not args.no_browser)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="apexlunar", description="Match Apex lunar lighting to the real moon.")
    p.add_argument("--config", type=Path, default=svc.DEFAULT_CONFIG)
    sub = p.add_subparsers(dest="cmd")
    w = sub.add_parser("web", help="run the local web app (default)")
    w.add_argument("--bind", default="127.0.0.1", help="0.0.0.0 to reach it from other devices")
    w.add_argument("--port", type=int, default=8788)
    w.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    m = sub.add_parser("moon", help="moon phase and rise/set for your location")
    m.add_argument("--date", help="YYYY-MM-DD (default: today on the controller)")
    m.add_argument("--utc-offset", type=float, help="hours; default: read from the Apex")
    for name in ("preview", "apply"):
        s = sub.add_parser(name, help="show (apply --write: send) a day's table")
        s.add_argument("--date", help="YYYY-MM-DD (default: today on the controller)")
        s.add_argument("--write", action="store_true", help="actually write to the Apex")
    r = sub.add_parser("restore", help="put a backed-up program back")
    r.add_argument("file")
    r.add_argument("--write", action="store_true")
    u = sub.add_parser("update", help="write today's table if needed (what the scheduler runs)")
    u.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    sc = sub.add_parser("schedule", help="install/remove the daily background update")
    sc.add_argument("action", choices=["install", "uninstall", "status", "run"])
    sc.add_argument("--at", help="HH:MM, computer clock (default from config, else 00:05)")
    args = p.parse_args(argv)
    if args.cmd is None:
        args = p.parse_args(["--config", str(args.config), "web"])  # double-click friendly
    if args.cmd == "preview":
        args.write = False
    try:
        cfg = svc.load_config(args.config)
        {"web": cmd_web, "moon": cmd_moon, "preview": cmd_apply, "apply": cmd_apply,
         "restore": cmd_restore, "update": cmd_update, "schedule": cmd_schedule}[args.cmd](cfg, args)
    except (ApexError, svc.ConfigError) as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
