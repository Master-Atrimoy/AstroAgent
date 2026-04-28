"""
All API routes for DeepSkyAgent.
/api/health           — system status
/api/locations/search — geocoding
/api/ollama/models    — available LLM models
/api/catalogue/...    — live catalogue management
/api/rightnow         — Tab 1: instant scorer
/api/plan/stream      — Tab 2: SSE-streamed LangGraph plan
"""
from __future__ import annotations
import json
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
import httpx

from backend.schemas.astro import RightNowRequest, PlanAheadRequest
from backend.tools.geocoder import search_locations
from backend.tools.catalogue import (
    get_catalogue, get_catalogue_by_category,
    get_status, build_live_catalogue, score_and_filter,
)
from backend.tools.horizons import (
    get_altitude, get_limiting_magnitude, get_bortle,
    score_altitude, score_seeing, score_darkness, score_equipment,
    score_darkness_for_object, get_moon_warning,
    get_twilight_status, get_scoring_datetime,
)
from backend.tools.weather import fetch_7day_forecast
from backend.tools.moon import get_moon_info
from backend.agents.equipment_resolver import resolve_equipment
from backend.agents.llm import get_available_models
from backend.agents.graph import get_graph
from backend.config.loader import get_config

log = logging.getLogger(__name__)
router = APIRouter()

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


# ── Health ─────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    ollama_ok = False
    models = []
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                ollama_ok = True
                models = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass

    cat_status = get_status()
    return {
        "status": "ok",
        "ollama": "connected" if ollama_ok else "offline — run: ollama serve",
        "ollama_url": OLLAMA_URL,
        "models_installed": models,
        "catalogue": cat_status,
        "time_utc": datetime.now(timezone.utc).isoformat(),
    }


# ── Location search ────────────────────────────────────────────────────────

@router.get("/locations/search")
async def location_search(q: str = Query(..., min_length=2)):
    results = await search_locations(q)
    return {"results": [r.model_dump() for r in results]}


# ── Ollama models ──────────────────────────────────────────────────────────

@router.get("/ollama/models")
async def ollama_models():
    models = await get_available_models(OLLAMA_URL)
    return {"models": models}


# ── Catalogue ──────────────────────────────────────────────────────────────

@router.get("/catalogue/status")
def catalogue_status():
    return get_status()


@router.get("/catalogue/refresh")
async def catalogue_refresh(
    lat: float = Query(0.0),
    lon: float = Query(0.0),
    background_tasks: BackgroundTasks = None,
):
    """Trigger a live catalogue rebuild in the background."""
    if background_tasks:
        background_tasks.add_task(build_live_catalogue, lat, lon)
    return {"message": "Catalogue refresh started", "status": "building"}


@router.get("/catalogue")
async def catalogue(
    lat: float = Query(0.0),
    lon: float = Query(0.0),
    aperture_mm: float = Query(150.0),
    sqm: float = Query(19.0),
    min_alt: float = Query(15.0),
    category: str = Query("all"),
):
    """Return scored catalogue filtered by location and visibility."""
    cfg = get_config()
    lim_mag = get_limiting_magnitude(aperture_mm, sqm)
    objects = get_catalogue()

    if category != "all":
        objects = [o for o in objects if o.category == category]

    scored = score_and_filter(objects, lat, lon, lim_mag, min_alt if min_alt > -90 else -90)
    by_cat = {}
    for obj in scored:
        c = obj["category"]
        by_cat.setdefault(c, [])
        by_cat[c].append(obj)

    return {
        "objects": scored,
        "by_category": by_cat,
        "count": len(scored),
        "limiting_magnitude": lim_mag,
        "bortle": get_bortle(sqm),
        "source": get_status().get("source", "fallback"),
    }


@router.get("/catalogue/categories")
def catalogue_categories():
    return {"categories": list(get_catalogue_by_category().keys())}


# ── Equipment resolver ─────────────────────────────────────────────────────

@router.post("/equipment/resolve")
async def equipment_resolve(payload: dict):
    """Resolve free-text equipment description via LLM."""
    raw = payload.get("raw_input", "")
    preset = payload.get("preset", "casual")
    model = payload.get("model", "llama3.2")

    loop = asyncio.get_event_loop()
    profile = await loop.run_in_executor(
        None, resolve_equipment, raw, preset, model, 30
    )
    return profile.model_dump()


# ── Tab 1: Right Now scorer ────────────────────────────────────────────────

def _compute_live_planets(lat: float, lon: float) -> dict:
    """Compute current planet positions via ephem. Returns dict keyed by planet ID."""
    from backend.schemas.astro import CatalogueObject
    import math as _math
    try:
        import ephem
        from datetime import datetime, timezone as tz
        obs = ephem.Observer()
        obs.lat = str(lat)
        obs.lon = str(lon)
        obs.date = datetime.now(tz.utc).strftime("%Y/%m/%d %H:%M:%S")
        obs.pressure = 0  # disable refraction for cleaner calcs

        planet_map = {
            "MER": (ephem.Mercury(),  "Mercury",  "Elusive inner planet, seen near horizon",        "Observe near greatest elongation", 60),
            "VEN": (ephem.Venus(),    "Venus",    "Brilliant evening/morning star, shows phases",    "Best observed in twilight to reduce glare", 60),
            "MAR": (ephem.Mars(),     "Mars",     "Red planet — best near opposition",               "Surface detail needs excellent seeing and 6\"+ aperture", 100),
            "JUP": (ephem.Jupiter(),  "Jupiter",  "Largest planet, visible cloud bands and 4 moons","High magnification; image during good seeing", 60),
            "SAT": (ephem.Saturn(),   "Saturn",   "Ringed giant — always spectacular",               "60x shows rings; 150x reveals Cassini Division", 60),
            "URA": (ephem.Uranus(),   "Uranus",   "Ice giant, appears as blue-green disk",           "200x+ needed for disk", 100),
            "NEP": (ephem.Neptune(),  "Neptune",  "Blue disk, Triton moon challenging",              "Appears as tiny blue-grey disk at 200x", 150),
        }

        results = {}
        for pid, (body, name, desc, notes, min_ap) in planet_map.items():
            body.compute(obs)
            ra_deg = _math.degrees(float(body.ra))
            dec_deg = _math.degrees(float(body.dec))
            mag = float(body.mag) if hasattr(body, "mag") else 5.0
            results[pid] = CatalogueObject(
                id=pid, name=name, category="planet",
                ra_deg=ra_deg, dec_deg=dec_deg,
                magnitude=round(mag, 1),
                angular_size_arcmin=0.5,
                description=desc,
                imaging_notes=notes,
                min_aperture_mm=min_ap,
                source="ephem",
            )
        return results
    except Exception as e:
        log.warning(f"ephem planet computation failed: {e}")
        return {}



@router.post("/rightnow")
async def right_now(req: RightNowRequest):
    """
    Instant observation scorer for Tab 1.
    Scores objects for the NEXT dark window (not current moment if daytime).
    """
    # ── Equipment ──────────────────────────────────────────────────────────
    if req.equipment_raw.strip():
        loop = asyncio.get_event_loop()
        equipment = await loop.run_in_executor(
            None, resolve_equipment,
            req.equipment_raw, req.equipment_preset, req.model, 20
        )
    else:
        from backend.schemas.astro import EQUIPMENT_PRESETS
        equipment = EQUIPMENT_PRESETS.get(
            req.equipment_preset, EQUIPMENT_PRESETS["casual"]
        ).model_copy()

    # ── Sun / twilight status ──────────────────────────────────────────────
    # Fix #1/#5: compute sun altitude and decide what time to score for
    now_utc = datetime.now(timezone.utc)
    twilight = get_twilight_status(req.lat, req.lon, now_utc)
    score_dt, is_tonight = get_scoring_datetime(req.lat, req.lon)
    is_daytime = twilight["is_daytime"]

    # ── Weather ────────────────────────────────────────────────────────────
    nights = await fetch_7day_forecast(req.lat, req.lon)
    # Use tonight's night score if daytime, else current hour
    if is_tonight and len(nights) > 0:
        night_data = nights[0]
        cloud_score = night_data.cloud_score
        seeing_est = (sum(h.seeing_estimate for h in night_data.hours) / len(night_data.hours)
                      if night_data.hours else 3.0)
        transp_est = (sum(h.transparency_estimate for h in night_data.hours) / len(night_data.hours)
                      if night_data.hours else 3.5)
    else:
        night_data = nights[0] if nights else None
        cloud_score = night_data.cloud_score if night_data else 70.0
        seeing_est  = night_data.hours[0].seeing_estimate if night_data and night_data.hours else 3.0
        transp_est  = night_data.hours[0].transparency_estimate if night_data and night_data.hours else 3.5

    current_conditions = {
        "cloud_score":  cloud_score,
        "seeing":       seeing_est,
        "transparency": transp_est,
        "sqm":          19.0,
    }

    moon = get_moon_info(req.lat, req.lon, score_dt.strftime("%Y-%m-%d"))

    # ── Live planet positions ──────────────────────────────────────────────
    loop = asyncio.get_event_loop()
    live_planets = await loop.run_in_executor(
        None, _compute_live_planets, req.lat, req.lon
    )

    # ── Build object list ──────────────────────────────────────────────────
    objects = get_catalogue()
    non_planets = [o for o in objects if o.category != "planet"]
    all_objects = list(live_planets.values()) + non_planets

    # Fix #2: resolve selected target object for narrative pinning
    selected_obj = None
    if req.target_id:
        selected_obj = next((o for o in all_objects if o.id == req.target_id), None)

    lim_mag = get_limiting_magnitude(equipment.aperture_mm, current_conditions["sqm"])
    scored = []

    WEIGHTS = {"altitude": 0.30, "seeing": 0.25, "darkness": 0.20,
               "equipment": 0.15, "affinity": 0.10}

    for obj in all_objects:
        if obj.magnitude > lim_mag + 4:
            continue

        # Score altitude at the scoring datetime (tonight if daytime now)
        alt = get_altitude(obj.ra_deg, obj.dec_deg, req.lat, req.lon, score_dt)

        # Always include selected target even if below threshold
        is_selected = selected_obj and obj.id == selected_obj.id
        if alt < 8 and not is_selected:
            continue

        # Fix #1/#6: flag planets visible during daytime
        is_planet = obj.category == "planet"
        sun_alt = twilight["sun_alt"]
        daytime_planet = is_planet and sun_alt > -6

        # Fix #4: use enhanced darkness scorer with low-SB penalty
        darkness_sc = score_darkness_for_object(
            current_conditions["sqm"],
            moon["illumination_pct"],
            obj_id=obj.id,
            angular_size_arcmin=obj.angular_size_arcmin,
            magnitude=obj.magnitude,
        )

        components = {
            "altitude":  score_altitude(alt),
            "seeing":    score_seeing(3, current_conditions["seeing"]),
            "darkness":  darkness_sc,
            "equipment": score_equipment(obj.min_aperture_mm, equipment.aperture_mm),
            "affinity":  0.7,
        }
        final = sum(WEIGHTS[k] * v for k, v in components.items())

        # Fix #7: compute moon warning badge
        moon_warn = get_moon_warning(
            moon["illumination_pct"], obj.id,
            obj.angular_size_arcmin, obj.magnitude
        )

        scored.append({
            **obj.model_dump(),
            "altitude_deg":   round(alt, 1),
            "score":          round(final * 100),
            "components":     {k: round(v, 3) for k, v in components.items()},
            "daytime_planet": daytime_planet,
            "moon_warning":   moon_warn,
            "scored_for":     score_dt.strftime("%H:%M UTC") if is_tonight else "now",
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:10]

    # ── Fix #2/#3: LLM narrative pinned to selected target ────────────────
    narrative = ""
    primary = selected_obj.model_dump() if selected_obj else (top[0] if top else None)
    primary_scored = next((o for o in scored if o["id"] == primary["id"]), None) if primary else None

    # If selected target not in scored list (e.g. below horizon tonight),
    # compute its altitude now and build a minimal scored entry for the narrative
    if selected_obj and not primary_scored:
        fallback_alt = get_altitude(selected_obj.ra_deg, selected_obj.dec_deg,
                                    req.lat, req.lon, score_dt)
        primary_scored = {
            **selected_obj.model_dump(),
            "altitude_deg": round(fallback_alt, 1),
            "score": 0,
            "components": {},
            "daytime_planet": selected_obj.category == "planet" and twilight["sun_alt"] > -6,
            "moon_warning": get_moon_warning(moon["illumination_pct"], selected_obj.id,
                                              selected_obj.angular_size_arcmin, selected_obj.magnitude),
            "scored_for": score_dt.strftime("%H:%M UTC") if is_tonight else "now",
        }

    if primary_scored:
        try:
            from backend.agents.llm import call_llm

            # If user selected a target — narrative IS about that target
            if selected_obj and primary_scored:
                focus_block = (
                    f"SELECTED TARGET (write about THIS specifically):\n"
                    f"  Name: {primary_scored['name']}\n"
                    f"  Type: {primary_scored['category']}\n"
                    f"  Score: {primary_scored['score']}/100\n"
                    f"  Altitude at {primary_scored['scored_for']}: {primary_scored['altitude_deg']}°\n"
                    f"  Magnitude: {primary_scored['magnitude']}\n"
                    f"  Moon warning: {primary_scored.get('moon_warning') or 'none'}\n"
                    f"  Daytime observation: {'yes — requires special filter' if primary_scored.get('daytime_planet') else 'no'}\n"
                )
                other_names = ", ".join(
                    o["name"] for o in top[:4] if o["id"] != primary_scored["id"]
                )
                context_block = f"Other visible objects for context: {other_names}\n"
                instruction = (
                    f"Write exactly 2-3 sentences ONLY about the selected target "
                    f"{primary_scored['name']}. "
                    f"Use the exact altitude and score numbers above. "
                    f"{'Mention it is a daytime/twilight target requiring a filter.' if primary_scored.get('daytime_planet') else ''}"
                    f"{'Mention: ' + primary_scored['moon_warning'] if primary_scored.get('moon_warning') else ''}"
                    f" Give one specific observing tip for the equipment. Plain prose only."
                )
            else:
                # No target selected — recommend the best one
                focus_block = (
                    f"Best target tonight:\n"
                    f"  Name: {primary_scored['name']} (score {primary_scored['score']}/100, "
                    f"altitude {primary_scored['altitude_deg']}°)\n"
                )
                other_names = ", ".join(o["name"] for o in top[1:4])
                context_block = f"Also visible: {other_names}\n"
                instruction = (
                    f"Write exactly 2 sentences recommending {primary_scored['name']} "
                    f"and give one practical observing tip. Plain prose only."
                )

            prompt = (
                f"You are a concise, precise astronomy observer assistant.\n"
                f"Observer: {req.equipment_preset} level, equipment: {equipment.scope_name}\n"
                f"Conditions: cloud {current_conditions['cloud_score']:.0f}/100, "
                f"seeing {current_conditions['seeing']:.1f}/5, "
                f"moon {moon['illumination_pct']:.0f}% lit, {twilight['label']}\n"
                f"Scoring for: {score_dt.strftime('%Y-%m-%d %H:%M UTC')}"
                f"{' (tonight — currently daytime)' if is_tonight else ''}\n\n"
                f"{focus_block}"
                f"{context_block}\n"
                f"{instruction}"
            )

            def _call():
                return call_llm(prompt, model=req.model, ollama_url=OLLAMA_URL, timeout=120)

            loop = asyncio.get_event_loop()
            narrative = await asyncio.wait_for(
                loop.run_in_executor(None, _call), timeout=125.0
            )
        except asyncio.TimeoutError:
            name = primary_scored["name"]
            narrative = (
                f"{'Selected target: ' if selected_obj else 'Top pick: '}"
                f"{name} — score {primary_scored['score']}/100 at "
                f"{primary_scored['altitude_deg']}° altitude "
                f"({'daytime — use solar/ND filter' if primary_scored.get('daytime_planet') else 'tonight'}). "
                f"[AI narrative timed out]"
            )
        except Exception as e:
            name = primary_scored["name"] if primary_scored else "Unknown"
            narrative = f"{name} (score {primary_scored['score'] if primary_scored else 0}/100). [{str(e)[:80]}]"

    return {
        "top_targets": top,
        "all_scored": scored,
        "narrative": narrative,
        "equipment": equipment.model_dump(),
        "twilight": twilight,
        "scored_for_dt": score_dt.isoformat(),
        "is_tonight": is_tonight,
        "conditions": {
            **current_conditions,
            "moon_pct": moon["illumination_pct"],
            "moon_rises": moon.get("rises"),
            "moon_sets": moon.get("sets"),
            "limiting_mag": lim_mag,
            "bortle": get_bortle(current_conditions["sqm"]),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Tab 2: Plan Ahead — SSE streaming ─────────────────────────────────────

async def _run_graph_stream(req: PlanAheadRequest) -> AsyncGenerator[str, None]:
    """Run LangGraph graph and yield SSE events as agents progress."""

    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    yield _sse({"event": "start", "message": "Starting AstroAgent pipeline…"})

    initial_state = {
        "lat": req.lat,
        "lon": req.lon,
        "target_id": req.target_id,
        "equipment_preset": req.equipment_preset,
        "equipment_raw": req.equipment_raw,
        "model": req.model,
        "ollama_timeout": req.ollama_timeout,
        "progress_events": [],
        "critique_loops": 0,
        "critic_warnings": [],
        "critic_passed": False,
        "error": None,
    }

    graph = get_graph()
    last_event_count = 0

    try:
        # Run graph in thread pool (nodes are sync)
        loop = asyncio.get_event_loop()
        final_state = await loop.run_in_executor(None, graph.invoke, initial_state)

        # Stream all progress events
        events = final_state.get("progress_events", [])
        for evt in events[last_event_count:]:
            yield _sse({"event": "progress", **evt})
            await asyncio.sleep(0.05)

        # Error state
        if final_state.get("error"):
            yield _sse({"event": "error", "message": final_state["error"]})
            return

        # Final plan
        plan = final_state.get("plan")
        if plan:
            # Generate final narrative if not already rich
            if not plan.narrative or len(plan.narrative) < 80:
                try:
                    from backend.agents.llm import call_llm
                    target = final_state.get("target")
                    equipment = final_state.get("equipment")
                    best = final_state.get("best_night")
                    prompt = (
                        f"Write a 3-4 sentence enthusiastic observation plan summary.\n"
                        f"Target: {target.name if target else 'Unknown'}\n"
                        f"Best night: {best.date if best else '?'} "
                        f"(score {best.overall_score if best else 0:.0f}/100)\n"
                        f"Equipment: {equipment.scope_name if equipment else '?'}\n"
                        f"ISO: {plan.recommended_iso}, Sub: {plan.recommended_sub_sec}s, "
                        f"Filter: {plan.recommended_filter}\n"
                        f"Warnings: {'; '.join(plan.critic_warnings) if plan.critic_warnings else 'none'}\n"
                        f"Plain prose only. Be specific and encouraging."
                    )
                    plan.narrative = call_llm(
                        prompt, model=req.model,
                        ollama_url=OLLAMA_URL, timeout=40
                    )
                except Exception:
                    pass

            yield _sse({
                "event": "plan",
                "plan": plan.model_dump(),
                "night_scores": [n.model_dump() for n in final_state.get("night_scores", [])],
                "equipment": final_state.get("equipment").model_dump() if final_state.get("equipment") else {},
            })
        else:
            yield _sse({"event": "error", "message": "No plan generated"})

    except Exception as e:
        log.exception("Graph execution failed")
        yield _sse({"event": "error", "message": str(e)})

    yield _sse({"event": "done", "message": "Complete"})


@router.post("/plan/stream")
async def plan_stream(req: PlanAheadRequest):
    """SSE endpoint — streams agent progress and final plan."""
    return StreamingResponse(
        _run_graph_stream(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
