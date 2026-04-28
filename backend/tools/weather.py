"""Open-Meteo weather fetcher — free, no API key required."""
from __future__ import annotations
import httpx
from datetime import datetime, timezone
from backend.schemas.astro import HourlyConditions, NightScore
from backend.config.loader import get_config


def _seeing_from_weather(wind_ms: float, cloud_pct: float) -> float:
    """Estimate seeing 1–5 from wind speed and cloud cover."""
    base = 5.0
    base -= min(2.0, wind_ms / 5.0)
    base -= min(1.5, cloud_pct / 100.0 * 2.0)
    return round(max(1.0, base), 1)


def _transparency_from_weather(cloud_pct: float, precip_mm: float) -> float:
    """Estimate transparency 1–5 from cloud and precipitation."""
    base = 5.0 - (cloud_pct / 100.0 * 3.5)
    if precip_mm > 0.1:
        base -= 1.5
    return round(max(1.0, min(5.0, base)), 1)


async def fetch_7day_forecast(lat: float, lon: float) -> list[NightScore]:
    """Fetch 7 days of hourly weather and return per-night scored summaries."""
    cfg = get_config()
    url = cfg.tools.open_meteo.forecast_url
    timeout = cfg.tools.open_meteo.timeout_sec

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "cloud_cover", "precipitation", "temperature_2m",
            "dew_point_2m", "wind_speed_10m", "weather_code",
        ]),
        "forecast_days": 7,
        "timezone": "UTC",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return []

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    clouds = hourly.get("cloud_cover", [])
    precips = hourly.get("precipitation", [])
    temps = hourly.get("temperature_2m", [])
    dews = hourly.get("dew_point_2m", [])
    winds = hourly.get("wind_speed_10m", [])

    # Group by date, only night hours (20:00–05:00 UTC approx)
    nights: dict[str, list[HourlyConditions]] = {}
    for i, t in enumerate(times):
        hour = int(t[11:13])
        date = t[:10]
        is_night = hour >= 20 or hour <= 5
        if not is_night:
            continue
        # Key: the observation night starts at 20:00 of the earlier date
        night_key = date if hour >= 20 else (
            datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
            .strftime("%Y-%m-%d")
        )
        hc = HourlyConditions(
            time_utc=t,
            cloud_cover_pct=float(clouds[i] if i < len(clouds) else 50),
            precipitation_mm=float(precips[i] if i < len(precips) else 0),
            temperature_c=float(temps[i] if i < len(temps) else 15),
            dew_point_c=float(dews[i] if i < len(dews) else 10),
            wind_speed_ms=float(winds[i] if i < len(winds) else 3),
            seeing_estimate=_seeing_from_weather(
                float(winds[i] if i < len(winds) else 3),
                float(clouds[i] if i < len(clouds) else 50),
            ),
            transparency_estimate=_transparency_from_weather(
                float(clouds[i] if i < len(clouds) else 50),
                float(precips[i] if i < len(precips) else 0),
            ),
        )
        nights.setdefault(night_key, []).append(hc)

    night_scores = []
    for date, hours in sorted(nights.items()):
        if not hours:
            continue
        avg_cloud = sum(h.cloud_cover_pct for h in hours) / len(hours)
        avg_seeing = sum(h.seeing_estimate for h in hours) / len(hours)
        avg_transp = sum(h.transparency_estimate for h in hours) / len(hours)
        any_precip = any(h.precipitation_mm > 0.1 for h in hours)

        cloud_score = max(0.0, 100.0 - avg_cloud)
        seeing_score = (avg_seeing / 5.0) * 100.0
        transp_score = (avg_transp / 5.0) * 100.0

        # Best window = longest run of hours with cloud < 30%
        clear_hours = [h for h in hours if h.cloud_cover_pct < 30]
        window_start = clear_hours[0].time_utc if clear_hours else ""
        window_end = clear_hours[-1].time_utc if clear_hours else ""

        night_scores.append(NightScore(
            date=date,
            overall_score=0.0,  # filled by PlanBuilder after moon penalty
            cloud_score=cloud_score,
            seeing_score=seeing_score,
            transparency_score=transp_score,
            altitude_score=0.0,  # filled by PlanBuilder
            moon_penalty=0.0,   # filled by PlanBuilder
            moon_illumination_pct=0.0,  # filled by moon.py
            best_window_start=window_start,
            best_window_end=window_end,
            hours=hours,
        ))
    return night_scores
