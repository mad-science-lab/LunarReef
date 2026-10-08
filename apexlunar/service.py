# Version: V26.281.0251
"""Shared logic for the CLI and the web app: config, planning, writing, backups."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .apex import Apex, ApexError
from .table import (TableSettings, build_rows, fmt_minute, parse_tdata, replace_tdata,
                    rise_set, sample_day)

ROOT = Path(__file__).resolve().parent.parent
# Where settings, backups, state and the log live. The project folder by default;
# the Home Assistant add-on points this at its persistent /data.
DATA_DIR = Path(os.environ.get("APEXLUNAR_DATA") or ROOT)
DEFAULT_CONFIG = DATA_DIR / "config.json"
EXAMPLE_CONFIG = ROOT / "config.example.json"
BACKUP_DIR = DATA_DIR / "backups"
STATE_FILE = DATA_DIR / "state.json"
ACTIVITY_LOG = DATA_DIR / "logs" / "activity.jsonl"
ACTIVITY_KEEP = 500  # lines kept in the activity log


class ConfigError(RuntimeError):
    pass


# ---------------------------------------------------------------- config

def home_assistant_location() -> tuple[float, float] | None:
    """Home Assistant's home lat/lon, when running as an add-on (needs homeassistant_api)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    import urllib.request
    req = urllib.request.Request("http://supervisor/core/api/config",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            c = json.load(r)
        return float(c["latitude"]), float(c["longitude"])
    except Exception:
        return None


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    if not path.exists():
        if path == DEFAULT_CONFIG and EXAMPLE_CONFIG.exists():
            cfg = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
            loc = home_assistant_location()  # first run in HA: start from HA's home
            if loc:
                cfg["location"] = {"latitude": round(loc[0], 4), "longitude": round(loc[1], 4)}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        else:
            raise ConfigError(f"No config at {path}. Copy config.example.json to config.json.")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("apex", {})
    cfg.setdefault("table", {})
    cfg.setdefault("schedule", {"apply_at": "00:05"})
    for key, env in (("host", "APEX_HOST"), ("username", "APEX_USER"), ("password", "APEX_PASSWORD")):
        if os.environ.get(env):
            cfg["apex"][key] = os.environ[env]
    return cfg


def save_config(cfg: dict, path: Path = DEFAULT_CONFIG) -> None:
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def settings_from(cfg: dict) -> TableSettings:
    t = cfg.get("table", {})
    return TableSettings(
        max_intensity=int(t.get("max_intensity", 15)),
        ramp_altitude_deg=float(t.get("ramp_altitude_deg", 10)),
        channels=t.get("channels") or None,
        max_rows=int(t.get("max_rows", 12)),
    )


def connect(cfg: dict) -> Apex:
    a = cfg["apex"]
    if not a.get("host"):
        raise ConfigError("Apex host is not set.")
    return Apex(a["host"], a.get("username", "admin"), a.get("password", ""))


def controller_day(offset_h: float, when: str | None = None) -> date:
    if when:
        return date.fromisoformat(when)
    return (datetime.now(timezone.utc) + timedelta(hours=offset_h)).date()


def channel_values(master: dict, settings: TableSettings) -> tuple[int, ...]:
    """Per-color values for the new rows, in the order the Apex lists the colors."""
    colors = [c["name"] for c in master.get("extra", {}).get("colors", [])]
    if settings.channels:
        unknown = set(settings.channels) - set(colors)
        if unknown:
            raise ConfigError(f"Unknown channel(s) {sorted(unknown)}; this light has {colors}")
        return tuple(int(settings.channels.get(c, 0)) for c in colors)
    rows = current_rows(master)
    if not rows:
        return tuple(100 for _ in colors)
    return max(rows, key=lambda r: r.intensity).channels[: len(colors)]


def current_rows(obj: dict):
    return [parse_tdata(l) for l in obj.get("prog", "").splitlines()
            if l.strip().lower().startswith("tdata")]


# ---------------------------------------------------------------- planning

def moon_summary(cfg: dict, offset_h: float, day: date, settings: TableSettings):
    lat, lon = float(cfg["location"]["latitude"]), float(cfg["location"]["longitude"])
    samples = sample_day(day, lat, lon, offset_h, settings)
    noon = samples[len(samples) // 2][2]
    rises, sets = rise_set(samples)
    peak_m, _, peak_s = max(samples, key=lambda s: s[2].altitude_deg)
    info = {
        "date": day.isoformat(), "latitude": lat, "longitude": lon, "utc_offset": offset_h,
        "phase": noon.phase_name, "illumination": round(noon.illumination, 3),
        "age_days": round(noon.age_days, 1), "waxing": noon.waxing,
        "elongation": round(noon.elongation_deg, 1),
        "rises": [fmt_minute(m) for m in rises], "sets": [fmt_minute(m) for m in sets],
        "peak_altitude": round(peak_s.altitude_deg, 1), "peak_time": fmt_minute(peak_m),
        "curve": [{"m": m, "alt": round(s.altitude_deg, 1), "v": round(v, 2)} for m, v, s in samples],
    }
    return info, samples


def row_dicts(rows, colors):
    return [{"time": fmt_minute(r.minute), "minute": r.minute, "intensity": r.intensity,
             "channels": dict(zip(colors, r.channels))} for r in rows]


def plan(cfg: dict, apex: Apex, when: str | None = None) -> dict:
    """Everything needed to show or apply a day's table. Reads only."""
    settings = settings_from(cfg)
    offset_h = apex.utc_offset_hours()
    day = controller_day(offset_h, when)
    info, samples = moon_summary(cfg, offset_h, day, settings)
    members = apex.group_members(cfg["apex"]["lunar_did"])
    master = members[0]
    colors = [c["name"] for c in master.get("extra", {}).get("colors", [])]
    rows = build_rows(samples, channel_values(master, settings), settings)
    return {
        "moon": info,
        "members": [{"did": m["did"], "name": m["name"], "gid": m.get("gid")} for m in members],
        "colors": colors,
        "current": row_dicts(current_rows(master), colors),
        "proposed": row_dicts(rows, colors),
        "_rows": rows, "_master": master,
    }


def public(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


# ---------------------------------------------------------------- writing

def backup(obj: dict) -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"{stamp}_{obj['did']}.json"
    path.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    return path


def write_prog(apex: Apex, did: str, prog: str, log: list[str]) -> dict:
    """GET the live object, back it up, PUT it with the new prog, read it back."""
    live = apex.get_output(did)
    log.append(f"  backup {backup(live).name}")
    live["prog"] = prog
    apex.put_output(live)
    return apex.get_output(did)


def apply(cfg: dict, apex: Apex, p: dict) -> list[str]:
    """Write a planned table to the group master, then make sure peers match."""
    log: list[str] = []
    master, rows = p["_master"], p["_rows"]
    new_prog = replace_tdata(master["prog"], rows)
    if master["prog"].strip() == new_prog.strip():
        log.append(f"{master['name']} ({master['did']}) already has this table - nothing to write")
        return log
    log.append(f"Writing {master['name']} ({master['did']})")
    after = write_prog(apex, master["did"], new_prog, log)
    if after["prog"].strip() != new_prog.strip():
        raise ApexError("read-back does not match what was written; restore from the backup")
    log.append("  verified")
    block = "\n".join(r.tdata() for r in rows)
    for peer in p["members"][1:]:
        live = apex.get_output(peer["did"])
        if block in live["prog"]:
            log.append(f"{peer['name']} ({peer['did']}) matches - the group copied it")
            continue
        log.append(f"{peer['name']} ({peer['did']}) still had the old table; writing it too")
        after = write_prog(apex, peer["did"], replace_tdata(live["prog"], rows), log)
        log.append("  verified" if block in after["prog"] else "  MISMATCH")
    return log


def list_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    out = []
    for f in sorted(BACKUP_DIR.glob("*.json"), reverse=True):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
            out.append({"file": f.name, "did": obj.get("did"), "name": obj.get("name"),
                        "rows": len(current_rows(obj))})
        except (OSError, ValueError):
            continue
    return out


def restore(apex: Apex, filename: str) -> list[str]:
    path = (BACKUP_DIR / filename).resolve()
    if path.parent != BACKUP_DIR.resolve() or not path.exists():
        raise ConfigError(f"no backup named {filename}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    log = [f"Restoring {obj['name']} ({obj['did']}) from {filename}"]
    after = write_prog(apex, obj["did"], obj["prog"], log)
    log.append("  verified" if after["prog"].strip() == obj["prog"].strip() else "  MISMATCH")
    return log


def light_outputs(apex: Apex) -> list[dict]:
    return [{"did": o["did"], "name": o["name"], "type": o.get("type"), "gid": o.get("gid")}
            for o in apex.outputs() if "Light" in str(o.get("type"))]


# ---------------------------------------------------------------- activity + state
# Shared by the web app (manual actions) and the scheduled `update` run, so the
# page shows what the background job did.

def log_activity(source: str, ok: bool, msg: str, lines: list[str] | None = None) -> None:
    ACTIVITY_LOG.parent.mkdir(exist_ok=True)
    entry = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source": source,
             "ok": ok, "msg": msg, "lines": lines or []}
    with ACTIVITY_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    all_lines = ACTIVITY_LOG.read_text(encoding="utf-8").splitlines()
    if len(all_lines) > ACTIVITY_KEEP:
        ACTIVITY_LOG.write_text("\n".join(all_lines[-ACTIVITY_KEEP:]) + "\n", encoding="utf-8")


def read_activity(limit: int = 50) -> list[dict]:
    try:
        lines = ACTIVITY_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines[-limit:]):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(**changes) -> None:
    state = read_state()
    state.update(changes)
    STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def apply_and_record(cfg: dict, source: str, when: str | None = None) -> list[str]:
    """Plan + apply for a day, then record the outcome. Raises on failure (after logging)."""
    stamp = datetime.now().isoformat(timespec="seconds")
    try:
        apex = connect(cfg)
        p = plan(cfg, apex, when)
        lines = apply(cfg, apex, p)
    except Exception as e:
        write_state(last_run_at=stamp, last_run_ok=False, last_error=str(e))
        log_activity(source, False, f"{source}: update failed - {e}")
        raise
    m = p["moon"]
    changed = not lines[0].endswith("nothing to write")
    write_state(last_run_at=stamp, last_run_ok=True, last_error=None, last_applied=m["date"],
                **({"last_written_at": stamp} if changed else {}))
    summary = (f"{source}: {'wrote' if changed else 'already current -'} table for {m['date']} "
               f"({m['phase']}, {m['illumination'] * 100:.0f}% lit, {len(p['proposed'])} rows)")
    log_activity(source, True, summary, lines)
    return [summary] + lines
