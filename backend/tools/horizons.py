"""Astronomical coordinate math — altitude, azimuth, LST, scoring."""
from __future__ import annotations
import math
from datetime import datetime, timezone


def get_julian_date(dt: datetime | None = None) -> float:
    if dt is None:
        dt = datetime.now(timezone.utc)
    a = (14 - dt.month) // 12
    y = dt.year + 4800 - a
    m = dt.month + 12 * a - 3
    jdn = (dt.day + (153 * m + 2) // 5 + 365 * y
           + y // 4 - y // 100 + y // 400 - 32045)
    frac = (dt.hour - 12) / 24 + dt.minute / 1440 + dt.second / 86400
    return jdn + frac


def get_lst(lon_deg: float, dt: datetime | None = None) -> float:
    jd = get_julian_date(dt)
    T = (jd - 2451545.0) / 36525
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545)
            + T * T * 0.000387933 - T ** 3 / 38710000)
    return (gmst + lon_deg + 360) % 360


def get_altitude(ra_deg: float, dec_deg: float,
                 lat_deg: float, lon_deg: float,
                 dt: datetime | None = None) -> float:
    lst = get_lst(lon_deg, dt)
    ha = math.radians((lst - ra_deg + 360) % 360)
    dec = math.radians(dec_deg)
    lat = math.radians(lat_deg)
    sin_alt = (math.sin(dec) * math.sin(lat)
               + math.cos(dec) * math.cos(lat) * math.cos(ha))
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


def get_azimuth(ra_deg: float, dec_deg: float,
                lat_deg: float, lon_deg: float,
                dt: datetime | None = None) -> float:
    lst = get_lst(lon_deg, dt)
    ha = math.radians((lst - ra_deg + 360) % 360)
    dec = math.radians(dec_deg)
    lat = math.radians(lat_deg)
    sin_az = -math.cos(dec) * math.sin(ha)
    cos_az = (math.sin(dec) * math.cos(lat)
              - math.cos(dec) * math.cos(ha) * math.sin(lat))
    az = math.degrees(math.atan2(sin_az, cos_az))
    return (az + 360) % 360


# ── Scoring helpers ────────────────────────────────────────────────────────

def score_altitude(alt: float) -> float:
    if alt < 15:
        return 0.0
    if alt < 30:
        return 0.2 * (alt - 15) / 15
    t = (alt - 30) / 60
    return min(1.0, 0.2 + 0.8 * (1 - math.exp(-3 * t)))


def score_seeing(obj_best_seeing: int, seeing: float) -> float:
    return min(1.0, seeing / obj_best_seeing) if obj_best_seeing > 0 else 1.0


def score_darkness(sqm: float, moon_pct: float) -> float:
    moon_penalty = max(0.0, (moon_pct - 50) / 100)
    base = (sqm - 14) / 8
    return max(0.0, min(1.0, base - moon_penalty))


def score_equipment(min_aperture: int, aperture_mm: float) -> float:
    if aperture_mm < min_aperture:
        return max(0.0, 0.5 - (min_aperture - aperture_mm) / 200)
    return min(1.0, 0.7 + (aperture_mm - min_aperture) / 200 * 0.3)


def get_limiting_magnitude(aperture_mm: float, sqm: float) -> float:
    base = 2.1 + 5 * math.log10(max(1, aperture_mm))
    return round(base + (sqm - 19) * 0.3, 1)


def get_bortle(sqm: float) -> str:
    if sqm >= 21.7: return "Bortle 1 — True dark sky"
    if sqm >= 21.3: return "Bortle 2 — Typical dark sky"
    if sqm >= 20.8: return "Bortle 3 — Rural sky"
    if sqm >= 20.3: return "Bortle 4 — Rural/suburban"
    if sqm >= 19.25: return "Bortle 5 — Suburban"
    if sqm >= 18.5: return "Bortle 6 — Bright suburban"
    if sqm >= 17.5: return "Bortle 7 — Suburban/urban"
    return "Bortle 8–9 — Urban"


# ── Sun / twilight helpers ─────────────────────────────────────────────────

def get_sun_altitude(lat_deg: float, lon_deg: float,
                     dt: datetime | None = None) -> float:
    """Return sun altitude in degrees. Negative = below horizon."""
    try:
        import ephem, math as _m
        obs = ephem.Observer()
        obs.lat = str(lat_deg)
        obs.lon = str(lon_deg)
        obs.pressure = 0
        if dt:
            obs.date = dt.strftime("%Y/%m/%d %H:%M:%S")
        sun = ephem.Sun(obs)
        sun.compute(obs)
        return round(_m.degrees(float(sun.alt)), 1)
    except Exception:
        # Fallback: rough approximation via LST
        return -30.0  # assume nighttime if ephem unavailable


def get_twilight_status(lat_deg: float, lon_deg: float,
                        dt: datetime | None = None) -> dict:
    """
    Returns dict with:
      sun_alt: current sun altitude (degrees)
      is_dark: True if astronomical twilight or darker (sun < -18)
      is_civil_twilight: sun between -6 and 0
      is_nautical_twilight: sun between -12 and -6
      is_astronomical_twilight: sun between -18 and -12
      label: human-readable description
      next_dark_start: ISO string of next astronomical darkness (UTC)
      next_dark_end: ISO string of next astronomical dawn (UTC)
    """
    from datetime import timedelta
    if dt is None:
        dt = datetime.now(timezone.utc)

    sun_alt = get_sun_altitude(lat_deg, lon_deg, dt)

    if sun_alt > 0:
        label = "Daytime"
    elif sun_alt > -6:
        label = "Civil twilight"
    elif sun_alt > -12:
        label = "Nautical twilight"
    elif sun_alt > -18:
        label = "Astronomical twilight"
    else:
        label = "Dark sky"

    is_dark = sun_alt <= -18

    # Find next astronomical darkness window (scan ahead hour by hour)
    next_dark_start = None
    next_dark_end = None
    try:
        check = dt
        found_start = is_dark  # already dark?
        if found_start:
            next_dark_start = dt.isoformat()
        for h in range(1, 30):  # scan up to 30 hours ahead
            check = dt + timedelta(hours=h)
            alt = get_sun_altitude(lat_deg, lon_deg, check)
            if not found_start and alt <= -18:
                next_dark_start = check.replace(minute=0, second=0).isoformat()
                found_start = True
            elif found_start and alt > -18 and next_dark_start:
                next_dark_end = check.replace(minute=0, second=0).isoformat()
                break
    except Exception:
        pass

    return {
        "sun_alt": sun_alt,
        "is_dark": is_dark,
        "is_daytime": sun_alt > 0,
        "label": label,
        "next_dark_start": next_dark_start,
        "next_dark_end": next_dark_end,
    }


def get_scoring_datetime(lat_deg: float, lon_deg: float) -> tuple[datetime, bool]:
    """
    Returns (dt_to_score, is_tonight).
    - Sun > -6 (daytime or civil twilight) → score for tonight's dark window
    - Sun <= -6 (nautical/astronomical twilight or dark) → score for NOW
      These are all valid observing conditions, just progressively better.
    """
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    twi = get_twilight_status(lat_deg, lon_deg, now)

    # Valid observing time: nautical twilight (-12) or darker
    # Only redirect to tonight if it's truly too bright to observe (sun > -6)
    if twi["sun_alt"] <= -6:
        return now, False  # score right now — it's dark enough

    # Sun > -6: daytime or civil twilight — find tonight's dark window
    if twi["next_dark_start"]:
        try:
            dt = datetime.fromisoformat(twi["next_dark_start"])
            return dt + timedelta(hours=1), True
        except Exception:
            pass
    # Fallback: assume 21:00 local (rough)
    tonight = now.replace(hour=21, minute=0, second=0, microsecond=0)
    if tonight < now:
        tonight = tonight + timedelta(days=1)
    return tonight, True


# ── Surface brightness penalty ─────────────────────────────────────────────

# Objects with high angular size and low SB that suffer badly under moonlight
_LOW_SB_IDS = {
    "M33", "M101", "M31", "NGC891", "M74", "M81", "M82",
    "MW_CORE", "MW_CYGNUS", "NGC4565", "M51",
}

def score_darkness_for_object(
    sqm: float,
    moon_pct: float,
    obj_id: str = "",
    angular_size_arcmin: float = 0,
    magnitude: float = 10,
) -> float:
    """Enhanced darkness score with low-SB penalty for large faint objects."""
    moon_penalty = max(0.0, (moon_pct - 50) / 100)
    base = (sqm - 14) / 8

    # Extra moon penalty for low surface brightness objects
    is_low_sb = (obj_id in _LOW_SB_IDS) or (angular_size_arcmin > 30 and magnitude > 7)
    if is_low_sb and moon_pct > 60:
        extra = (moon_pct - 60) / 100 * 0.6  # up to 0.6 extra penalty
        moon_penalty += extra

    return max(0.0, min(1.0, base - moon_penalty))


def get_moon_warning(moon_pct: float, obj_id: str = "",
                     angular_size_arcmin: float = 0,
                     magnitude: float = 10) -> str | None:
    """Return a warning string if moon significantly impacts this object."""
    is_low_sb = (obj_id in _LOW_SB_IDS) or (angular_size_arcmin > 30 and magnitude > 7)
    if moon_pct > 90:
        return "🌕 Near full moon — only bright targets suitable"
    if moon_pct > 70 and is_low_sb:
        return "🌔 Moon too bright for this low surface-brightness object"
    if moon_pct > 70:
        return "🌔 High moon — contrast reduced"
    return None
