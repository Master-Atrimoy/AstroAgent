"""Moon phase, rise/set times, and angular separation from target using ephem."""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Optional


def _ephem_available() -> bool:
    try:
        import ephem
        return True
    except ImportError:
        return False


def get_moon_info(lat: float, lon: float, date_str: str) -> dict:
    """Return moon illumination, rise time, set time for a given night."""
    if not _ephem_available():
        return _fallback_moon(date_str)

    import ephem
    obs = ephem.Observer()
    obs.lat = str(lat)
    obs.lon = str(lon)
    obs.date = date_str + " 20:00:00"
    obs.horizon = "-0:34"  # standard refraction

    moon = ephem.Moon(obs)
    illumination = round(moon.phase, 1)

    try:
        rise = str(ephem.localtime(obs.next_rising(moon)))[:16]
    except Exception:
        rise = None

    try:
        setting = str(ephem.localtime(obs.next_setting(moon)))[:16]
    except Exception:
        setting = None

    return {
        "illumination_pct": illumination,
        "rises": rise,
        "sets": setting,
    }


def get_moon_separation_deg(
    target_ra_deg: float,
    target_dec_deg: float,
    lat: float,
    lon: float,
    date_str: str,
) -> float:
    """Angular separation in degrees between moon and target at midnight."""
    if not _ephem_available():
        return 90.0  # safe fallback

    import ephem
    obs = ephem.Observer()
    obs.lat = str(lat)
    obs.lon = str(lon)
    obs.date = date_str + " 23:00:00"

    moon = ephem.Moon(obs)
    moon.compute(obs)

    moon_ra = math.degrees(float(moon.ra))
    moon_dec = math.degrees(float(moon.dec))

    # Haversine angular separation
    ra1, dec1 = math.radians(moon_ra), math.radians(moon_dec)
    ra2, dec2 = math.radians(target_ra_deg), math.radians(target_dec_deg)
    dra = ra2 - ra1
    ddec = dec2 - dec1
    a = math.sin(ddec / 2) ** 2 + math.cos(dec1) * math.cos(dec2) * math.sin(dra / 2) ** 2
    return round(math.degrees(2 * math.asin(math.sqrt(a))), 1)


def _fallback_moon(date_str: str) -> dict:
    """Rough moon phase calculation without ephem."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        known_new = datetime(2024, 1, 11, tzinfo=timezone.utc)
        days_since = (dt - known_new).days % 29.53
        phase = abs(math.cos(math.pi * days_since / 29.53)) * 100
        return {"illumination_pct": round(phase, 1), "rises": None, "sets": None}
    except Exception:
        return {"illumination_pct": 50.0, "rises": None, "sets": None}
