# Version: V26.281.0141
"""Turn a day of moon positions into an Apex light control table.

An Apex light program is a list of `tdata` rows:

    tdata HH:MM:SS,0,0,<intensity>,<ch1>,...,<ch10>

The controller ramps linearly between rows and wraps at midnight. Rows are in
the controller's local time, so callers pass the controller's UTC offset.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .moon import MoonState, moon_state

CHANNEL_SLOTS = 10
DAY_MINUTES = 24 * 60
LAST_MINUTE = DAY_MINUTES - 1  # 23:59, matches what Fusion writes


@dataclass(frozen=True)
class TableSettings:
    max_intensity: int = 15        # master % at full moon, overhead
    ramp_altitude_deg: float = 10  # moon reaches full brightness at this altitude
    channels: dict | None = None   # {"White": 0, "Blue": 100}; None = keep current mix
    max_rows: int = 12
    sample_minutes: int = 5


@dataclass(frozen=True)
class Row:
    minute: int
    intensity: int
    channels: tuple[int, ...]

    def tdata(self) -> str:
        hh, mm = divmod(self.minute, 60)
        vals = list(self.channels) + [0] * (CHANNEL_SLOTS - len(self.channels))
        return f"tdata {hh:02d}:{mm:02d}:00,0,0,{self.intensity}," + ",".join(str(v) for v in vals)


def parse_tdata(line: str) -> Row:
    """Parse one `tdata` line from an Apex program."""
    body = line.split(None, 1)[1]
    parts = body.split(",")
    hh, mm, _ss = (int(x) for x in parts[0].split(":"))
    return Row(hh * 60 + mm, int(float(parts[3])), tuple(int(float(v)) for v in parts[4:]))


def brightness(state: MoonState, settings: TableSettings) -> float:
    """Master intensity (float %) for one moment: illumination x height above horizon."""
    if state.altitude_deg <= 0:
        return 0.0
    height = min(state.altitude_deg / settings.ramp_altitude_deg, 1.0)
    return settings.max_intensity * state.illumination * height


def sample_day(day: date, lat: float, lon: float, utc_offset_h: float,
               settings: TableSettings) -> list[tuple[int, float, MoonState]]:
    """(minute-of-local-day, intensity, state) every sample_minutes, plus 23:59."""
    tz = timezone(timedelta(hours=utc_offset_h))
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    minutes = list(range(0, DAY_MINUTES, settings.sample_minutes))
    if minutes[-1] != LAST_MINUTE:
        minutes.append(LAST_MINUTE)
    out = []
    for m in minutes:
        st = moon_state(start + timedelta(minutes=m), lat, lon)
        out.append((m, brightness(st, settings), st))
    return out


def _simplify(points: list[tuple[int, float]], tol: float) -> list[tuple[int, float]]:
    """Douglas-Peucker on (minute, intensity); keeps both endpoints."""
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    worst, idx = -1.0, 0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        interp = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        if abs(y - interp) > worst:
            worst, idx = abs(y - interp), i
    if worst <= tol:
        return [points[0], points[-1]]
    return _simplify(points[: idx + 1], tol)[:-1] + _simplify(points[idx:], tol)


def build_rows(samples: list[tuple[int, float, MoonState]], channels: tuple[int, ...],
               settings: TableSettings) -> list[Row]:
    """Fewest rows (<= max_rows) whose linear ramps track the moon curve."""
    pts = [(m, v) for m, v, _ in samples]
    tol = 0.6  # rows are whole percents, so finer is noise
    keep = _simplify(pts, tol)
    while len(keep) > settings.max_rows:
        tol *= 1.5
        keep = _simplify(pts, tol)
    rows: list[Row] = []
    for m, v in keep:
        row = Row(m, int(round(v)), channels)
        if not rows or rows[-1].minute != row.minute:
            rows.append(row)
    return rows


def rise_set(samples: list[tuple[int, float, MoonState]]) -> tuple[list[int], list[int]]:
    """Minutes-of-day where the moon crosses the horizon (linear interpolation)."""
    rises, sets = [], []
    for (m0, _, s0), (m1, _, s1) in zip(samples, samples[1:]):
        a0, a1 = s0.altitude_deg, s1.altitude_deg
        if (a0 <= 0) != (a1 <= 0):
            t = m0 + (m1 - m0) * (0 - a0) / (a1 - a0)
            (rises if a1 > a0 else sets).append(int(round(t)))
    return rises, sets


def replace_tdata(prog: str, rows: list[Row]) -> str:
    """Swap the tdata block in an Apex program, leaving every other line alone."""
    lines = prog.replace("\r\n", "\n").split("\n")
    out, inserted = [], False
    for line in lines:
        if line.strip().lower().startswith("tdata"):
            if not inserted:
                out.extend(r.tdata() for r in rows)
                inserted = True
            continue
        out.append(line)
    if not inserted:  # no table yet: put it after Fallback (or at the top)
        at = next((i + 1 for i, l in enumerate(out) if l.strip().lower().startswith("fallback")), 0)
        out[at:at] = [r.tdata() for r in rows]
    return "\n".join(out)


def fmt_minute(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"
