"""
DSO catalogue + altitude calculations.
astropy used when installed, pure-math fallback otherwise.
"""
from __future__ import annotations
import math
import re
from datetime import datetime, timedelta
from typing import Optional

try:
    from astropy.coordinates import SkyCoord, EarthLocation, AltAz, get_body
    from astropy.time import Time
    import astropy.units as u
    _ASTROPY = True
except ImportError:
    _ASTROPY = False

try:
    import ephem as _ephem
    _EPHEM = True
except ImportError:
    _EPHEM = False

# ── Catalogue ─────────────────────────────────────────────────────────────────
DSO_CATALOGUE: dict[str, dict] = {
    "m31":                  {"name":"M31 — Andromeda Galaxy","ra":10.685,"dec":41.269,"type":"galaxy","mag":3.4,"size":189.0},
    "andromeda galaxy":     {"name":"M31 — Andromeda Galaxy","ra":10.685,"dec":41.269,"type":"galaxy","mag":3.4,"size":189.0},
    "andromeda":            {"name":"M31 — Andromeda Galaxy","ra":10.685,"dec":41.269,"type":"galaxy","mag":3.4,"size":189.0},
    "m42":                  {"name":"M42 — Orion Nebula","ra":83.822,"dec":-5.391,"type":"nebula","mag":4.0,"size":65.0},
    "orion nebula":         {"name":"M42 — Orion Nebula","ra":83.822,"dec":-5.391,"type":"nebula","mag":4.0,"size":65.0},
    "m45":                  {"name":"M45 — Pleiades","ra":56.850,"dec":24.117,"type":"cluster","mag":1.6,"size":110.0},
    "pleiades":             {"name":"M45 — Pleiades","ra":56.850,"dec":24.117,"type":"cluster","mag":1.6,"size":110.0},
    "m51":                  {"name":"M51 — Whirlpool Galaxy","ra":202.470,"dec":47.195,"type":"galaxy","mag":8.4,"size":11.2},
    "whirlpool":            {"name":"M51 — Whirlpool Galaxy","ra":202.470,"dec":47.195,"type":"galaxy","mag":8.4,"size":11.2},
    "m57":                  {"name":"M57 — Ring Nebula","ra":283.396,"dec":33.029,"type":"nebula","mag":8.8,"size":1.4},
    "ring nebula":          {"name":"M57 — Ring Nebula","ra":283.396,"dec":33.029,"type":"nebula","mag":8.8,"size":1.4},
    "m13":                  {"name":"M13 — Hercules Cluster","ra":250.423,"dec":36.461,"type":"cluster","mag":5.8,"size":20.0},
    "hercules cluster":     {"name":"M13 — Hercules Cluster","ra":250.423,"dec":36.461,"type":"cluster","mag":5.8,"size":20.0},
    "m27":                  {"name":"M27 — Dumbbell Nebula","ra":299.901,"dec":22.721,"type":"nebula","mag":7.4,"size":8.0},
    "dumbbell nebula":      {"name":"M27 — Dumbbell Nebula","ra":299.901,"dec":22.721,"type":"nebula","mag":7.4,"size":8.0},
    "m33":                  {"name":"M33 — Triangulum Galaxy","ra":23.462,"dec":30.660,"type":"galaxy","mag":5.7,"size":70.8},
    "triangulum":           {"name":"M33 — Triangulum Galaxy","ra":23.462,"dec":30.660,"type":"galaxy","mag":5.7,"size":70.8},
    "m81":                  {"name":"M81 — Bode's Galaxy","ra":148.888,"dec":69.065,"type":"galaxy","mag":6.9,"size":21.0},
    "bode":                 {"name":"M81 — Bode's Galaxy","ra":148.888,"dec":69.065,"type":"galaxy","mag":6.9,"size":21.0},
    "m82":                  {"name":"M82 — Cigar Galaxy","ra":148.970,"dec":69.680,"type":"galaxy","mag":8.4,"size":11.2},
    "cigar galaxy":         {"name":"M82 — Cigar Galaxy","ra":148.970,"dec":69.680,"type":"galaxy","mag":8.4,"size":11.2},
    "ngc7000":              {"name":"NGC 7000 — North America Nebula","ra":314.700,"dec":44.300,"type":"nebula","mag":4.0,"size":120.0},
    "north america nebula": {"name":"NGC 7000 — North America Nebula","ra":314.700,"dec":44.300,"type":"nebula","mag":4.0,"size":120.0},
    "m78":                  {"name":"M78 — Reflection Nebula","ra":86.683,"dec":0.079,"type":"nebula","mag":8.3,"size":8.0},
    "m64":                  {"name":"M64 — Black Eye Galaxy","ra":194.182,"dec":21.683,"type":"galaxy","mag":8.5,"size":10.0},
    "m101":                 {"name":"M101 — Pinwheel Galaxy","ra":210.802,"dec":54.349,"type":"galaxy","mag":7.9,"size":28.8},
    "pinwheel":             {"name":"M101 — Pinwheel Galaxy","ra":210.802,"dec":54.349,"type":"galaxy","mag":7.9,"size":28.8},
    "saturn":               {"name":"Saturn","ra":None,"dec":None,"type":"planet","mag":-0.4,"size":0.3},
    "jupiter":              {"name":"Jupiter","ra":None,"dec":None,"type":"planet","mag":-2.4,"size":0.7},
    "mars":                 {"name":"Mars","ra":None,"dec":None,"type":"planet","mag":0.5,"size":0.1},
    "venus":                {"name":"Venus","ra":None,"dec":None,"type":"planet","mag":-4.0,"size":0.3},
    "moon":                 {"name":"Moon","ra":None,"dec":None,"type":"moon","mag":-12.7,"size":30.0},
}

_FOCAL_RECS = [
    (120.0,  "200–500mm"),
    (40.0,   "500–1000mm"),
    (10.0,   "800–1500mm"),
    (3.0,    "1200–2500mm"),
    (0.0,    "1500–3000mm"),
]


def focal_recommendation(size_arcmin: Optional[float], obj_type: str = "") -> str:
    if not size_arcmin:
        return "600–1500mm"
    for threshold, rec in _FOCAL_RECS:
        if size_arcmin >= threshold:
            return rec
    return "1500–3000mm"


def resolve_target(query: str, lat: float, lon: float, date_str: str) -> dict:
    key = re.sub(r"\s+", " ", query.strip().lower())
    entry = DSO_CATALOGUE.get(key)
    if not entry:
        for k, v in DSO_CATALOGUE.items():
            if k in key or key in k:
                entry = v
                break
    if not entry:
        return dict(name=query, object_type="other", ra_deg=0.0, dec_deg=0.0,
                    magnitude=None, angular_size_arcmin=None, resolved=False,
                    recommended_focal_length_mm=None,
                    notes=f"'{query}' not in catalogue. Try M31, M42, Orion Nebula, etc.")

    entry = dict(entry)
    if entry.get("type") in ("planet","moon") and entry.get("ra") is None:
        entry["ra"], entry["dec"] = _planet_position(entry["name"].split("—")[0].strip().lower(), date_str)

    return dict(
        name=entry["name"],
        object_type=entry.get("type","other"),
        ra_deg=float(entry.get("ra") or 0.0),
        dec_deg=float(entry.get("dec") or 0.0),
        magnitude=entry.get("mag"),
        angular_size_arcmin=entry.get("size"),
        recommended_focal_length_mm=focal_recommendation(entry.get("size"), entry.get("type","")),
        notes="",
        resolved=True,
    )


def _planet_position(name: str, date_str: str) -> tuple[float, float]:
    if _ASTROPY:
        try:
            t = Time(date_str)
            coord = get_body(name, t)
            return float(coord.ra.deg), float(coord.dec.deg)
        except Exception:
            pass
    if _EPHEM:
        try:
            bodies = {"saturn":_ephem.Saturn,"jupiter":_ephem.Jupiter,
                      "mars":_ephem.Mars,"venus":_ephem.Venus,"moon":_ephem.Moon}
            cls = bodies.get(name)
            if cls:
                b = cls(date_str)
                return math.degrees(b.ra), math.degrees(b.dec)
        except Exception:
            pass
    # Rough approximation
    return 0.0, 0.0


def compute_altitude_schedule(
    ra_deg: float, dec_deg: float,
    lat: float, lon: float,
    date_str: str,
    hours: int = 12,
) -> list[dict]:
    if _ASTROPY and (ra_deg != 0.0 or dec_deg != 0.0):
        try:
            loc = EarthLocation(lat=lat*u.deg, lon=lon*u.deg)
            tgt = SkyCoord(ra=ra_deg*u.deg, dec=dec_deg*u.deg, frame="icrs")
            base = Time(date_str + " 18:00:00", scale="utc")
            out = []
            for i in range(hours * 2):
                t = base + i * 0.5 * u.hour
                frm = AltAz(obstime=t, location=loc)
                aa = tgt.transform_to(frm)
                out.append({"utc": t.datetime.strftime("%H:%M"),
                             "altitude_deg": round(float(aa.alt.deg), 1),
                             "azimuth_deg":  round(float(aa.az.deg),  1)})
            return out
        except Exception:
            pass
    return _altitude_math(ra_deg, dec_deg, lat, lon, date_str, hours)


def _altitude_math(ra_deg, dec_deg, lat, lon, date_str, hours) -> list[dict]:
    lat_r = math.radians(lat)
    dec_r = math.radians(dec_deg)
    try:
        base = datetime.strptime(date_str + " 18:00:00", "%Y-%m-%d %H:%M:%S")
    except Exception:
        base = datetime.utcnow().replace(hour=18, minute=0, second=0)
    out = []
    for i in range(hours * 2):
        t = base + timedelta(minutes=30*i)
        jd = 2451545.0 + (t - datetime(2000,1,1,12)).total_seconds()/86400
        gmst = (18.697374558 + 24.06570982441908*(jd-2451545.0)) % 24
        lst  = (gmst + lon/15.0) % 24
        ha_r = math.radians((lst - ra_deg/15.0) * 15)
        sin_alt = (math.sin(lat_r)*math.sin(dec_r) +
                   math.cos(lat_r)*math.cos(dec_r)*math.cos(ha_r))
        alt = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))
        az  = math.degrees(math.atan2(
            -math.cos(dec_r)*math.sin(ha_r),
            math.sin(dec_r)*math.cos(lat_r) - math.cos(dec_r)*math.cos(ha_r)*math.sin(lat_r)
        )) % 360
        out.append({"utc": t.strftime("%H:%M"),
                     "altitude_deg": round(alt, 1),
                     "azimuth_deg":  round(az,  1)})
    return out


def compute_transit_time(ra_deg: float, lat: float, lon: float, date_str: str) -> str:
    sched = compute_altitude_schedule(ra_deg, 0, lat, lon, date_str, 12)
    if not sched:
        return "00:00"
    return max(sched, key=lambda s: s["altitude_deg"])["utc"]
