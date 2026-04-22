"""Moon phase, illumination, rise/set, separation."""
from __future__ import annotations
import math
from datetime import datetime

try:
    import ephem as _ephem
    _EPHEM = True
except ImportError:
    _EPHEM = False


def get_moon_info(lat: float, lon: float, date_str: str,
                   target_ra: float = None, target_dec: float = None) -> dict:
    if _EPHEM:
        return _ephem_moon(lat, lon, date_str, target_ra, target_dec)
    return _math_moon(lat, lon, date_str, target_ra, target_dec)


def _ephem_moon(lat, lon, date_str, target_ra, target_dec) -> dict:
    try:
        obs = _ephem.Observer()
        obs.lat = str(lat); obs.lon = str(lon)
        obs.date = date_str + " 20:00:00"
        moon = _ephem.Moon(obs)
        illum = round(moon.phase, 1)
        try:    rise = _ephem.Date(obs.next_rising(moon)).datetime().strftime("%H:%M")
        except: rise = None
        try:    setting = _ephem.Date(obs.next_setting(moon)).datetime().strftime("%H:%M")
        except: setting = None
        sep = None
        if target_ra is not None and target_dec is not None:
            tgt = _ephem.FixedBody()
            tgt._ra  = math.radians(target_ra)
            tgt._dec = math.radians(target_dec)
            tgt.compute(obs)
            sep = round(math.degrees(_ephem.separation(moon, tgt)), 1)
        return {"illumination_pct": illum, "phase_name": _phase(illum),
                "rise_utc": rise, "set_utc": setting,
                "separation_from_target_deg": sep,
                "is_problematic": illum > 60 or (sep is not None and sep < 30)}
    except Exception:
        return _math_moon(lat, lon, date_str, target_ra, target_dec)


def _math_moon(lat, lon, date_str, target_ra, target_dec) -> dict:
    try: dt = datetime.strptime(date_str, "%Y-%m-%d")
    except: dt = datetime.utcnow()
    jd = 2451545.0 + (dt - datetime(2000,1,1,12)).total_seconds()/86400
    lunar_age = (jd - 2451550.1) % 29.53058867
    illum = round(50*(1 - math.cos(2*math.pi*lunar_age/29.53)), 1)
    moon_ra  = (lunar_age/29.53*360) % 360
    moon_dec = 23.5*math.sin(math.radians(moon_ra))
    sep = None
    if target_ra is not None and target_dec is not None:
        cos_sep = (math.sin(math.radians(target_dec))*math.sin(math.radians(moon_dec)) +
                   math.cos(math.radians(target_dec))*math.cos(math.radians(moon_dec))*
                   math.cos(math.radians(target_ra - moon_ra)))
        sep = round(math.degrees(math.acos(max(-1.0, min(1.0, cos_sep)))), 1)
    return {"illumination_pct": illum, "phase_name": _phase(illum),
            "rise_utc": None, "set_utc": None,
            "separation_from_target_deg": sep,
            "is_problematic": illum > 60 or (sep is not None and sep < 30)}


def _phase(illum: float) -> str:
    if illum < 5:   return "New Moon"
    if illum < 25:  return "Waxing Crescent"
    if illum < 45:  return "First Quarter"
    if illum < 55:  return "Waxing Gibbous"
    if illum < 75:  return "Waning Gibbous"
    if illum < 95:  return "Waning Gibbous"
    return "Full Moon"
