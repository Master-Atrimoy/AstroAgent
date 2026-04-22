"""Agent 2 — PlanBuilderAgent. Scores nights, builds ImagingPlan."""
from __future__ import annotations
import logging
from typing import Any, Optional

log = logging.getLogger("astroagent.planner")

_PLAN_PROMPT = """You are an astrophotography expert. Given the target, equipment, and best observing window, produce imaging settings.

TARGET: {name} ({type}, mag {mag}, {size} arcmin)
EQUIPMENT: {ap}mm f/{fr} {mount}, max sub {max_sub}s, sensor={sensor}
BEST NIGHT: {date}, {start}-{end} UTC, {hours}h usable, cloud {cloud}%, seeing {see}/5
MOON: {moon_pct}% illuminated (sets {moon_set})
TRANSIT (peak altitude): {transit} UTC

Return ONLY this JSON object:
{{
  "recommended_iso": <int for DSLR/mirrorless, null for dedicated_astro/mobile>,
  "recommended_gain": <int for dedicated_astro, null otherwise>,
  "recommended_sub_seconds": <int, MUST be <= {max_sub}>,
  "recommended_sub_count": <int>,
  "total_integration_minutes": <float>,
  "filter_recommendation": "<no filter|CLS clip-in|Ha narrowband|UHC|L-eNhance|IDAS>",
  "framing_notes": "<specific framing advice>",
  "cardinal_direction": "<compass direction at transit>",
  "setup_time_utc": "<HH:MM>",
  "dew_risk": "<low|medium|high>",
  "dew_heater_recommended": <true|false>,
  "reasoning_summary": "<2 sentences: why this night, any caveats>"
}}
Rules:
- sub_seconds <= {max_sub} always
- DSLR f/10: ISO 1600. DSLR f/5-7: ISO 800. Mobile: ISO auto (null)
- Moon > 40% + nebula target: use narrowband
- Dobsonian/mobile: sub_seconds <= 5, no filter
- dew_heater: true if seeing good + dew_risk medium/high"""


def run_plan_builder(state: dict, cfg: Any) -> dict:
    from ..schemas.astro import TargetInfo, EquipmentProfile, NightWindow, ImagingPlan
    from ..tools.horizons import compute_altitude_schedule, compute_transit_time
    from ..tools.weather import fetch_weather_windows
    from ..tools.moon import get_moon_info

    target    = TargetInfo(**state["target_info"])
    equipment = EquipmentProfile(**state["equipment_profile"])
    lat, lon  = state["lat"], state["lon"]
    pcfg      = cfg.agent.planner

    # Apply any revised constraints from critic
    critique = state.get("critique_result") or {}
    for k, v in critique.get("revised_constraints", {}).items():
        pass  # reserved for future constraint relaxation

    # Fetch weather
    nights = fetch_weather_windows(
        lat, lon, days=int(pcfg.target_window_days),
        url=cfg.tools.weather.open_meteo_url,
        timeout_s=int(cfg.tools.weather.timeout_s),
    )

    # Score each night
    scored: list[NightWindow] = []
    for night in nights:
        moon  = get_moon_info(lat, lon, night["date"], target.ra_deg, target.dec_deg)
        sched = compute_altitude_schedule(target.ra_deg, target.dec_deg, lat, lon, night["date"])
        w = _score_window(night, moon, sched, target, equipment, pcfg)
        if w:
            scored.append(w)

    if not scored:
        return {**state, "error": "No usable observing windows in the next 7 nights. Try a different target or location."}

    scored.sort(key=lambda w: w.overall_score, reverse=True)
    best   = scored[0]
    backup = scored[1] if len(scored) > 1 else None
    transit = compute_transit_time(target.ra_deg, lat, lon, best.date)

    # Ask LLM for narrative/settings
    llm_data = _get_llm_fields(target, equipment, best, transit, state)

    # Enforce mount limit regardless of LLM output
    max_sub = equipment.max_recommended_sub_sec
    sub_s   = min(llm_data.get("recommended_sub_seconds") or max_sub, max_sub)
    sub_n   = llm_data.get("recommended_sub_count") or max(1, int(120*60/sub_s))

    plan = ImagingPlan(
        target=target,
        best_window=best,
        backup_window=backup,
        equipment=equipment,
        recommended_iso=llm_data.get("recommended_iso"),
        recommended_gain=llm_data.get("recommended_gain"),
        recommended_sub_seconds=sub_s,
        recommended_sub_count=sub_n,
        total_integration_minutes=float(llm_data.get("total_integration_minutes") or round(sub_s*sub_n/60,1)),
        filter_recommendation=llm_data.get("filter_recommendation") or _default_filter(equipment, best),
        framing_notes=llm_data.get("framing_notes") or "Centre target and use live view to compose.",
        cardinal_direction=llm_data.get("cardinal_direction") or "South",
        transit_time_utc=transit,
        setup_time_utc=llm_data.get("setup_time_utc") or best.start_utc,
        dew_risk=llm_data.get("dew_risk") or best.date and "low",
        dew_heater_recommended=bool(llm_data.get("dew_heater_recommended", False)),
        reasoning_summary=llm_data.get("reasoning_summary") or
            f"Best window on {best.date} with score {best.overall_score}/10.",
    )

    return {
        **state,
        "night_windows":   [w.model_dump() for w in scored],
        "imaging_plan":    plan.model_dump(),
        "weather_windows": [dict(n) for n in nights],
    }


def _score_window(night: dict, moon: dict, sched: list, target, equipment, pcfg) -> Optional[Any]:
    from ..schemas.astro import NightWindow
    min_alt = float(pcfg.min_altitude_deg)
    usable  = [h for h in sched if h["altitude_deg"] >= min_alt]
    if not usable or len(usable)*0.5 < float(pcfg.min_session_hours):
        return None

    max_alt    = max(h["altitude_deg"] for h in usable)
    cloud      = float(night.get("avg_cloud_pct", 50))
    seeing     = int(night.get("seeing_score", 3))
    transp     = int(night.get("transparency_score", 3))
    moon_illum = float(moon["illumination_pct"])
    moon_sep   = float(moon.get("separation_from_target_deg") or 180.0)

    cloud_s  = (100-cloud)/10
    see_s    = seeing*2
    trans_s  = transp*2
    mp       = 2 if moon_illum>60 else (1 if moon_illum>30 else 0)
    if moon_sep < 30: mp += 2
    alt_b    = min(1.0, (max_alt-min_alt)/30)
    overall  = round(max(0.0, min(10.0, cloud_s*.4 + see_s*.3 + trans_s*.2 + alt_b - mp)), 1)

    if cloud > 60:                            limiting = "clouds"
    elif moon_illum > 60 or moon_sep < 30:    limiting = "moon"
    elif seeing < 3:                           limiting = "seeing"
    elif max_alt < 35:                         limiting = "altitude"
    else:                                      limiting = "none"

    return NightWindow(
        date=night["date"],
        start_utc=usable[0]["utc"],
        end_utc=usable[-1]["utc"],
        duration_hours=round(len(usable)*0.5, 1),
        target_max_altitude_deg=round(max_alt, 1),
        moon_illumination_pct=moon_illum,
        moon_rise_utc=moon.get("rise_utc"),
        moon_set_utc=moon.get("set_utc"),
        cloud_cover_pct=cloud,
        seeing_score=seeing,
        transparency_score=transp,
        overall_score=overall,
        limiting_factor=limiting,
    )


def _get_llm_fields(target, equipment, best, transit, state) -> dict:
    from .llm import call_llm, parse_json_output
    from pydantic import BaseModel
    from typing import Optional as Opt

    class _LLMOut(BaseModel):
        recommended_iso: Opt[int] = None
        recommended_gain: Opt[int] = None
        recommended_sub_seconds: int = 120
        recommended_sub_count: int = 60
        total_integration_minutes: float = 120.0
        filter_recommendation: str = "no filter"
        framing_notes: str = ""
        cardinal_direction: str = "South"
        setup_time_utc: str = "20:00"
        dew_risk: str = "low"
        dew_heater_recommended: bool = False
        reasoning_summary: str = ""

    max_sub = equipment.max_recommended_sub_sec
    prompt = _PLAN_PROMPT.format(
        name=target.name, type=target.object_type,
        mag=target.magnitude or "?", size=target.angular_size_arcmin or "?",
        ap=equipment.aperture_mm, fr=equipment.focal_ratio,
        mount=equipment.mount_type, max_sub=max_sub,
        sensor=equipment.sensor_type,
        date=best.date, start=best.start_utc, end=best.end_utc,
        hours=best.duration_hours, cloud=best.cloud_cover_pct,
        see=best.seeing_score,
        moon_pct=best.moon_illumination_pct,
        moon_set=best.moon_set_utc or "before dark",
        transit=transit,
    )
    try:
        raw = call_llm(prompt, state["ollama_model"], state["ollama_base_url"],
                       timeout=state.get("ollama_timeout", 90))
        result = parse_json_output(raw, _LLMOut)
        if result.recommended_sub_seconds > max_sub:
            result.recommended_sub_seconds = max_sub
        return result.model_dump()
    except Exception as e:
        log.warning("LLM plan fields failed (%s): %s — using fallback", type(e).__name__, e)
        return _fallback_fields(equipment, best, target, transit)


def _default_filter(equipment, best) -> str:
    if equipment.mount_type in ("dobsonian",) or equipment.sensor_type == "mobile":
        return "no filter"
    if best.moon_illumination_pct > 40:
        return "Ha narrowband"
    return "no filter"


def _fallback_fields(equipment, best, target, transit) -> dict:
    max_sub = equipment.max_recommended_sub_sec
    sub_n   = max(1, int(120*60/max_sub))
    iso     = None
    if equipment.sensor_type in ("dslr","mirrorless"):
        iso = 1600 if equipment.focal_ratio >= 8 else 800
    return {
        "recommended_iso": iso, "recommended_gain": None,
        "recommended_sub_seconds": max_sub, "recommended_sub_count": sub_n,
        "total_integration_minutes": round(max_sub*sub_n/60, 1),
        "filter_recommendation": _default_filter(equipment, best),
        "framing_notes": f"Centre {target.name.split('—')[0].strip()} in FOV. Use live view to compose.",
        "cardinal_direction": "South",
        "setup_time_utc": best.start_utc,
        "dew_risk": best.dew_risk if hasattr(best,"dew_risk") else "low",
        "dew_heater_recommended": False,
        "reasoning_summary": f"Best window: {best.date}, score {best.overall_score}/10, target peaks at {best.target_max_altitude_deg}°.",
    }
