"""Weather tool — Open-Meteo with synthetic fallback."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any


def fetch_weather_windows(lat: float, lon: float, days: int = 7,
                           url: str = "https://api.open-meteo.com/v1/forecast",
                           timeout_s: int = 10) -> list[dict]:
    try:
        import httpx
        params = {
            "latitude": lat, "longitude": lon,
            "hourly": ["cloudcover","relativehumidity_2m","dewpoint_2m",
                       "temperature_2m","windspeed_10m","precipitation_probability"],
            "forecast_days": days, "timezone": "UTC",
        }
        r = httpx.get(url, params=params, timeout=timeout_s)
        r.raise_for_status()
        return _parse_nightly(r.json(), days)
    except Exception:
        return _synthetic(days)


def _parse_nightly(data: dict, days: int) -> list[dict]:
    h = data.get("hourly", {})
    times   = h.get("time", [])
    cloud   = h.get("cloudcover", [])
    humid   = h.get("relativehumidity_2m", [])
    dew     = h.get("dewpoint_2m", [])
    temp    = h.get("temperature_2m", [])
    wind    = h.get("windspeed_10m", [])
    precip  = h.get("precipitation_probability", [])

    nights: dict[str, list] = {}
    for i, ts in enumerate(times):
        hour = int(ts[11:13])
        if not (hour >= 18 or hour < 6):
            continue
        date_part = ts[:10]
        astro_date = date_part if hour >= 18 else (
            (datetime.strptime(date_part, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        )
        nights.setdefault(astro_date, []).append({
            "utc":       ts[11:16],
            "cloud_pct": cloud[i]  if i < len(cloud) else 50,
            "humid_pct": humid[i]  if i < len(humid) else 70,
            "dew_c":     dew[i]    if i < len(dew)   else 10,
            "temp_c":    temp[i]   if i < len(temp)   else 15,
            "wind_kmh":  wind[i]   if i < len(wind)   else 10,
            "precip":    precip[i] if i < len(precip) else 5,
        })

    result = []
    for date, hours in list(nights.items())[:days]:
        result.append({"date": date, **_score_night(hours)})
    return result


def _score_night(hours: list[dict]) -> dict:
    if not hours:
        return dict(avg_cloud_pct=80.0, seeing_score=2, transparency_score=2,
                    best_start_utc="20:00", best_end_utc="23:00",
                    dew_risk="medium", dew_heater_recommended=True, hours=[])

    avg_cloud = sum(h["cloud_pct"] for h in hours) / len(hours)
    avg_wind  = sum(h["wind_kmh"]  for h in hours) / len(hours)
    avg_humid = sum(h["humid_pct"] for h in hours) / len(hours)

    # Best 4-hour window
    best_start = hours[0].get("utc","20:00")
    best_end   = hours[min(3,len(hours)-1)].get("utc","23:00")
    best_cloud = avg_cloud
    for i in range(max(1,len(hours)-3)):
        w = hours[i:i+4]
        wc = sum(x["cloud_pct"] for x in w) / len(w)
        if wc < best_cloud:
            best_cloud = wc
            best_start = w[0].get("utc","20:00")
            best_end   = w[-1].get("utc","23:00")

    # Seeing 1-5: penalise wind + humidity
    seeing = 5
    if avg_wind > 30: seeing -= 2
    elif avg_wind > 15: seeing -= 1
    if avg_humid > 90: seeing -= 1
    seeing = max(1, seeing)

    # Transparency 1-5: inverse of cloud cover
    transparency = max(1, min(5, 5 - int(avg_cloud/25)))

    # Dew risk: temp - dewpoint
    margins = [h["temp_c"] - h["dew_c"] for h in hours if h["temp_c"] and h["dew_c"]]
    min_margin = min(margins) if margins else 5.0
    dew_risk = "high" if min_margin < 3 else ("medium" if min_margin < 6 else "low")

    return dict(
        avg_cloud_pct=round(avg_cloud, 1),
        seeing_score=seeing,
        transparency_score=transparency,
        best_start_utc=best_start,
        best_end_utc=best_end,
        dew_risk=dew_risk,
        dew_heater_recommended=min_margin < 5,
        hours=hours,
    )


def _synthetic(days: int) -> list[dict]:
    import random; random.seed(42)
    profiles = [(15,5,5),(25,4,4),(60,2,2),(8,5,5),(35,3,3),(80,1,1),(20,4,4)]
    base = datetime.utcnow()
    out = []
    for i in range(days):
        cloud, see, transp = profiles[i % len(profiles)]
        cloud = max(0, cloud + random.randint(-5,5))
        hours = [{"utc":f"{h:02d}:00","cloud_pct":cloud,"humid_pct":65,"dew_c":8,
                  "temp_c":20,"wind_kmh":8,"precip":3}
                 for h in [20,21,22,23,0,1]]
        out.append({
            "date": (base+timedelta(days=i)).strftime("%Y-%m-%d"),
            "avg_cloud_pct": float(cloud),
            "seeing_score": see, "transparency_score": transp,
            "best_start_utc": "20:00", "best_end_utc": "02:00",
            "dew_risk": "low" if i%3 else "medium",
            "dew_heater_recommended": i%3==0,
            "hours": hours,
        })
    return out
