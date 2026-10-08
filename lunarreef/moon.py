# Version: V26.281.0130
"""Moon position, phase and visibility for a given place and time.

Pure standard library so it runs unchanged on Windows, macOS and Raspberry Pi.
Lunar position: Meeus, *Astronomical Algorithms* ch. 47 (main periodic terms,
~0.01 deg). Sun: Meeus ch. 25 low-precision. Plenty for driving a moonlight.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

D2R = math.pi / 180.0
R2D = 180.0 / math.pi
SYNODIC_DAYS = 29.530588853
EARTH_RADIUS_KM = 6378.14
AU_KM = 149_597_870.7

# Meeus table 47.A: D, M, M', F, sum-l (1e-6 deg), sum-r (1e-3 km)
_LR = (
    (0, 0, 1, 0, 6288774, -20905355), (2, 0, -1, 0, 1274027, -3699111),
    (2, 0, 0, 0, 658314, -2955968), (0, 0, 2, 0, 213618, -569925),
    (0, 1, 0, 0, -185116, 48888), (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158), (2, -1, -1, 0, 57066, -152138),
    (2, 0, 1, 0, 53322, -170733), (2, -1, 0, 0, 45758, -204586),
    (0, 1, -1, 0, -40923, -129620), (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755), (2, 0, 0, -2, 15327, 10321),
    (0, 0, 1, 2, -12528, 0), (0, 0, 1, -2, 10980, 79661),
    (4, 0, -1, 0, 10675, -34782), (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636), (2, 1, -1, 0, -7888, 24208),
    (2, 1, 0, 0, -6766, 30824), (1, 0, -1, 0, -5163, -8379),
    (1, 1, 0, 0, 4987, -16675), (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445), (4, 0, 0, 0, 3861, -11650),
    (2, 0, -3, 0, 3665, 14403), (0, 1, -2, 0, -2689, -7003),
    (2, 0, -1, 2, -2602, 0), (2, -1, -2, 0, 2390, 10056),
    (1, 0, 1, 0, -2348, 6322), (2, -2, 0, 0, 2236, -9884),
)
# Meeus table 47.B: D, M, M', F, sum-b (1e-6 deg)
_B = (
    (0, 0, 0, 1, 5128122), (0, 0, 1, 1, 280602), (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237), (2, 0, -1, 1, 55413), (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573), (0, 0, 2, 1, 17198), (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822), (2, -1, 0, -1, 8216), (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200), (2, 1, 0, -1, -3359), (2, -1, -1, 1, 2463),
    (2, -1, 0, 1, 2211), (2, -1, -1, -1, 2065), (0, 1, -1, -1, -1870),
    (4, 0, -1, -1, 1828), (0, 1, 0, 1, -1794), (0, 0, 0, 3, -1749),
    (0, 1, -1, 1, -1565), (1, 0, 0, 1, -1491), (0, 1, 1, 1, -1475),
    (0, 1, 1, -1, -1410), (0, 1, 0, -1, -1344), (1, 0, 0, -1, -1335),
    (0, 0, 3, 1, 1107),
)

PHASE_NAMES = (
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
)


@dataclass(frozen=True)
class MoonState:
    when: datetime
    altitude_deg: float      # topocentric, refraction-corrected
    azimuth_deg: float       # from north, eastward
    illumination: float      # 0..1 illuminated fraction
    elongation_deg: float    # 0 new, 180 full, measured eastward from the sun
    distance_km: float

    @property
    def waxing(self) -> bool:
        return self.elongation_deg < 180.0

    @property
    def age_days(self) -> float:
        return self.elongation_deg / 360.0 * SYNODIC_DAYS

    @property
    def phase_name(self) -> str:
        return PHASE_NAMES[int(((self.elongation_deg + 22.5) % 360) // 45)]


def julian_day(when: datetime) -> float:
    if when.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return when.timestamp() / 86400.0 + 2440587.5


def _moon_ecliptic(T: float) -> tuple[float, float, float]:
    """Geocentric ecliptic longitude, latitude (deg) and distance (km)."""
    Lp = (218.3164477 + 481267.88123421 * T) % 360
    D = (297.8501921 + 445267.1114034 * T) % 360
    M = (357.5291092 + 35999.0502909 * T) % 360
    Mp = (134.9633964 + 477198.8675055 * T) % 360
    F = (93.2720950 + 483202.0175233 * T) % 360
    E = 1 - 0.002516 * T - 0.0000074 * T * T
    A1 = (119.75 + 131.849 * T) % 360
    A2 = (53.09 + 479264.290 * T) % 360
    A3 = (313.45 + 481266.484 * T) % 360

    sl = sr = sb = 0.0
    for d, m, mp, f, cl, cr in _LR:
        arg = (d * D + m * M + mp * Mp + f * F) * D2R
        e = E ** abs(m)
        sl += cl * e * math.sin(arg)
        sr += cr * e * math.cos(arg)
    for d, m, mp, f, cb in _B:
        sb += cb * E ** abs(m) * math.sin((d * D + m * M + mp * Mp + f * F) * D2R)

    sl += 3958 * math.sin(A1 * D2R) + 1962 * math.sin((Lp - F) * D2R) + 318 * math.sin(A2 * D2R)
    sb += (-2235 * math.sin(Lp * D2R) + 382 * math.sin(A3 * D2R)
           + 175 * math.sin((A1 - F) * D2R) + 175 * math.sin((A1 + F) * D2R)
           + 127 * math.sin((Lp - Mp) * D2R) - 115 * math.sin((Lp + Mp) * D2R))
    return (Lp + sl / 1e6) % 360, sb / 1e6, 385000.56 + sr / 1000.0


def _sun_ecliptic(T: float) -> tuple[float, float]:
    """Geocentric ecliptic longitude (deg) and distance (km) of the sun."""
    L0 = 280.46646 + 36000.76983 * T
    M = 357.52911 + 35999.05029 * T
    C = ((1.914602 - 0.004817 * T) * math.sin(M * D2R)
         + (0.019993 - 0.000101 * T) * math.sin(2 * M * D2R)
         + 0.000289 * math.sin(3 * M * D2R))
    e = 0.016708634 - 0.000042037 * T
    nu = (M + C) * D2R
    r_au = 1.000001018 * (1 - e * e) / (1 + e * math.cos(nu))
    return (L0 + C) % 360, r_au * AU_KM


def moon_state(when: datetime, lat: float, lon: float) -> MoonState:
    """Moon as seen from lat/lon (degrees, east and north positive) at `when`."""
    jd = julian_day(when)
    T = (jd - 2451545.0) / 36525.0
    lam, beta, dist = _moon_ecliptic(T)
    lam_s, r_sun = _sun_ecliptic(T)

    # Phase from sun-moon geometry.
    elong = (lam - lam_s) % 360
    psi = math.acos(math.cos(beta * D2R) * math.cos((lam - lam_s) * D2R))
    i = math.atan2(r_sun * math.sin(psi), dist - r_sun * math.cos(psi))
    illum = (1 + math.cos(i)) / 2

    # Ecliptic -> equatorial.
    eps = (23.439291 - 0.0130042 * T) * D2R
    lr, br = lam * D2R, beta * D2R
    ra = math.atan2(math.sin(lr) * math.cos(eps) - math.tan(br) * math.sin(eps), math.cos(lr))
    dec = math.asin(math.sin(br) * math.cos(eps) + math.cos(br) * math.sin(eps) * math.sin(lr))

    # Equatorial -> horizontal.
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * T * T) % 360
    H = ((gmst + lon) * D2R - ra)
    phi = lat * D2R
    alt = math.asin(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(H))
    az = math.atan2(-math.sin(H) * math.cos(dec),
                    math.cos(phi) * math.sin(dec) - math.sin(phi) * math.cos(dec) * math.cos(H))

    # Topocentric parallax (up to ~1 deg for the moon), then refraction.
    alt_deg = alt * R2D - math.asin(EARTH_RADIUS_KM / dist * math.cos(alt)) * R2D
    if alt_deg > -1.0:
        alt_deg += 1.02 / math.tan((alt_deg + 10.3 / (alt_deg + 5.11)) * D2R) / 60.0

    return MoonState(when, alt_deg, (az * R2D) % 360, illum, elong, dist)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
