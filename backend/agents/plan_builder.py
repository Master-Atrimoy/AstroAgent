"""
PlanBuilderAgent — LangGraph node.
Fetches 7-night forecast, scores each night, selects best window.
Calls LLM for ISO/sub-length/filter recommendations.
"""
from __future__ import annotations
import os
import asyncio
import logging
from datetime import datetime, timezone

from backend.schemas.state import AstroState
from backend.schemas.astro import ObservationPlan, NightScore
from backend.tools.weather import fetch_7day_forecast
from backend.tools.moon import get_moon_info, get_moon_separation_deg
from backend.tools.horizons import get_altitude, score_altitude
from backend.agents.llm import call_llm, parse_json_output
from backend.config.loader import get_config

log = logging.getLogger(__name__)


def _score_night(
    night: NightScore,
    target_ra: float,
    target_dec: float,
    lat: float,
    lon: float,
    weights: dict,
) -> NightScore:
    """Apply moon penalty + altitude score to a NightScore."""
    # Moon info
    moon = get_moon_info(lat, lon, night.date)
    moon_pct = moon["illumination_pct"]
    moon_penalty = max(0.0, (moon_pct - 30) / 70) * 30  # up to 30pt penalty

    # Altitude score: compute target altitude at midnight
    try:
        from datetime import datetime
        midnight = datetime.strptime(night.date + " 23:00:00", "%Y-%m-%d %H:%M:%S")
        midnight = midnight.replace(tzinfo=timezone.utc)
        alt = get_altitude(target_ra, target_dec, lat, lon, midnight)
        alt_score = score_altitude(alt) * 100
    except Exception:
        alt_score = 50.0

    # Weighted overall
    overall = (
        night.cloud_score * weights["cloud"]
        + night.seeing_score * weights["seeing"]
        + night.transparency_score * weights["transparency"]
        + alt_score * weights["altitude"]
        - moon_penalty
    )

    moon_info = get_moon_info(lat, lon, night.date)

    return NightScore(
        **{
            **night.model_dump(),
            "overall_score": round(max(0.0, overall), 1),
            "altitude_score": round(alt_score, 1),
            "moon_penalty": round(moon_penalty, 1),
            "moon_illumination_pct": moon_pct,
            "moon_rises": moon_info.get("rises"),
            "moon_sets": moon_info.get("sets"),
        }
    )


def _llm_imaging_params(
    target_name: str,
    equipment,
    best_night: NightScore,
    model: str,
    timeout: int,
) -> dict:
    """Ask LLM for ISO, sub-length, filter, dew risk."""
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    prompt = f"""Given this astrophotography scenario, return ONLY a JSON object:

Target: {target_name}
Equipment: {equipment.scope_name}, aperture {equipment.aperture_mm}mm, focal {equipment.focal_length_mm}mm
Camera: {equipment.camera_name}, sensor {equipment.sensor_w_mm}x{equipment.sensor_h_mm}mm, pixel {equipment.pixel_size_um}um
Mount max unguided: {equipment.max_unguided_sub_sec}s, guided: {equipment.has_guiding}
Night conditions: cloud {best_night.cloud_score:.0f}/100, seeing {best_night.seeing_score:.0f}/100
Moon: {best_night.moon_illumination_pct:.0f}% illuminated
Temperature: check dew risk

Return JSON: {{"iso": number, "sub_sec": number, "filter": "string", "dew_risk": boolean, "reasoning": "string"}}"""

    try:
        raw = call_llm(prompt, model=model, ollama_url=ollama_url, timeout=timeout)
        return parse_json_output(raw)
    except Exception as e:
        log.warning(f"LLM imaging params failed: {e}")
        return {
            "iso": 800,
            "sub_sec": min(equipment.max_unguided_sub_sec, 60),
            "filter": "None",
            "dew_risk": False,
            "reasoning": "Default parameters (LLM unavailable)",
        }


def plan_builder_node(state: AstroState) -> AstroState:
    """Node 2: score 7 nights, pick best window, get LLM imaging params."""
    if state.get("error"):
        return state

    events = list(state.get("progress_events", []))
    events.append({"agent": "PlanBuilder", "status": "running",
                   "message": "Fetching 7-night weather forecast…"})

    cfg = get_config()
    weights = dict(cfg.agent.planner.night_score_weights)
    lat = state["lat"]
    lon = state["lon"]
    target = state["target"]
    equipment = state["equipment"]
    model = state.get("model", "llama3.2")
    timeout = state.get("ollama_timeout", 60)

    # Fetch weather
    loop = asyncio.new_event_loop()
    try:
        nights = loop.run_until_complete(fetch_7day_forecast(lat, lon))
    finally:
        loop.close()

    if not nights:
        events.append({"agent": "PlanBuilder", "status": "error",
                       "message": "Weather fetch failed — using fallback scores"})
        # Create dummy nights
        from datetime import timedelta
        today = datetime.now(timezone.utc)
        nights = []
        for i in range(7):
            d = (today + timedelta(days=i)).strftime("%Y-%m-%d")
            nights.append(NightScore(
                date=d, overall_score=50, cloud_score=60, seeing_score=60,
                transparency_score=60, altitude_score=60,
                moon_penalty=10, moon_illumination_pct=30,
            ))

    events.append({"agent": "PlanBuilder", "status": "running",
                   "message": f"Scoring {len(nights)} nights with moon and altitude data…"})

    # Score each night
    scored = [
        _score_night(n, target.ra_deg, target.dec_deg, lat, lon, weights)
        for n in nights
    ]
    scored.sort(key=lambda n: n.overall_score, reverse=True)

    best = scored[0] if scored else None
    backup = scored[1] if len(scored) > 1 else None

    events.append({"agent": "PlanBuilder", "status": "running",
                   "message": f"Best night: {best.date if best else '?'} (score {best.overall_score if best else 0:.0f}/100). Getting imaging parameters…"})

    # LLM imaging params
    params = _llm_imaging_params(target.name, equipment, best, model, timeout)

    plan = ObservationPlan(
        target=target,
        equipment=equipment,
        best_night=best,
        backup_night=backup,
        recommended_iso=int(params.get("iso", 800)),
        recommended_sub_sec=int(params.get("sub_sec", 60)),
        recommended_filter=str(params.get("filter", "None")),
        dew_risk=bool(params.get("dew_risk", False)),
        narrative=str(params.get("reasoning", "")),
        critic_warnings=[],
        critique_loops=state.get("critique_loops", 0),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    events.append({"agent": "PlanBuilder", "status": "done",
                   "message": f"Plan built — best window {best.best_window_start if best else '?'} UTC"})

    return {
        **state,
        "night_scores": scored,
        "best_night": best,
        "backup_night": backup,
        "plan": plan,
        "progress_events": events,
    }
