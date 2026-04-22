"""
AstroAgent v2 — All API routes.
SSE streaming — agents run synchronously in a thread, result passed via simple holder dict.
"""
from __future__ import annotations
import json
import logging
import uuid
from typing import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

log = logging.getLogger("astroagent.routes")
router = APIRouter()

# In-memory session store
_sessions: dict[str, dict] = {}


# ── Request/Response models ───────────────────────────────────────────────────

class SessionReq(BaseModel):
    ollama_model: str    = "llama3.1"
    ollama_base_url: str = "http://localhost:11434"


class PlanReq(BaseModel):
    session_id: str
    target: str
    location: str
    lat: float
    lon: float
    timezone_offset: int = 0
    equipment: str
    date_preference: str = "this weekend"
    ollama_model: str    = "llama3.1"
    ollama_base_url: str = "http://localhost:11434"
    ollama_timeout: int  = 90


# ── Session ───────────────────────────────────────────────────────────────────

@router.post("/session")
async def create_session(req: SessionReq):
    sid = str(uuid.uuid4())
    _sessions[sid] = {"session_id": sid, "model": req.ollama_model,
                      "base_url": req.ollama_base_url, "result": None}
    return {"session_id": sid}


@router.get("/session/{sid}")
async def get_session(sid: str):
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    return s


# ── Ollama model discovery ─────────────────────────────────────────────────────

@router.get("/ollama/models")
async def get_ollama_models(base_url: str = "http://localhost:11434"):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{base_url.rstrip('/')}/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
        priority = ["llama3.1","llama3.2","mistral","gemma2","qwen2.5","deepseek"]
        models.sort(key=lambda m: next((i for i,p in enumerate(priority) if m.startswith(p)), 99))
        return {"models": models, "status": "ok", "count": len(models)}
    except Exception as e:
        return {"models": [], "status": "error",
                "message": f"Cannot reach Ollama at {base_url}: {e}"}


# ── Location search ───────────────────────────────────────────────────────────

@router.get("/locations/search")
async def search_locations(q: str = "", limit: int = 8):
    """Proxy to Open-Meteo geocoding for location autocomplete."""
    if not q or len(q.strip()) < 2:
        return {"results": []}
    from ..tools.geocoder import search_locations as _search
    results = await _search(q.strip(), limit)
    return {"results": results}


# ── Target catalogue ──────────────────────────────────────────────────────────

@router.get("/targets")
async def list_targets():
    from ..tools.horizons import DSO_CATALOGUE
    seen: set[str] = set()
    out = []
    for k, v in DSO_CATALOGUE.items():
        if v["name"] not in seen:
            seen.add(v["name"])
            out.append({"key": k, "name": v["name"], "type": v.get("type",""),
                         "magnitude": v.get("mag"), "size_arcmin": v.get("size")})
    return {"targets": out}


# ── Equipment presets ─────────────────────────────────────────────────────────

@router.get("/equipment/presets")
async def list_equipment_presets():
    from ..agents.target_analyst import EQUIPMENT_PRESETS
    categories: dict[str, list] = {}
    for key, ep in EQUIPMENT_PRESETS.items():
        cat = ep.get("category", "other")
        categories.setdefault(cat, []).append({
            "key": key,
            "name": ep.get("preset_name", key),
            "aperture_mm": ep["aperture_mm"],
            "focal_length_mm": ep["focal_length_mm"],
            "focal_ratio": ep["focal_ratio"],
            "mount_type": ep["mount_type"],
            "max_sub_sec": ep["max_recommended_sub_sec"],
        })
    return {"categories": categories}


# ── Plan — SSE streaming ──────────────────────────────────────────────────────

@router.get("/plan")
def plan_get(
    request: Request,
    session_id: str = "", target: str = "", location: str = "",
    lat: float = 0.0, lon: float = 0.0, timezone_offset: int = 0,
    equipment: str = "", date_preference: str = "this weekend",
    ollama_model: str = "llama3.1", ollama_base_url: str = "http://localhost:11434",
    ollama_timeout: int = 90,
):
    body = PlanReq(
        session_id=session_id, target=target, location=location,
        lat=lat, lon=lon, timezone_offset=timezone_offset,
        equipment=equipment, date_preference=date_preference,
        ollama_model=ollama_model, ollama_base_url=ollama_base_url,
        ollama_timeout=ollama_timeout,
    )
    return _stream_plan(body, request)


@router.post("/plan")
def plan_post(body: PlanReq, request: Request):
    return _stream_plan(body, request)


def _stream_plan(body: PlanReq, request: Request) -> StreamingResponse:

    def gen() -> Iterator[str]:
        # Validate inputs early
        if not body.target.strip():
            yield _sse("error", {"message": "Target is required."}); return
        if not body.equipment.strip():
            yield _sse("error", {"message": "Equipment is required."}); return
        if body.lat == 0.0 and body.lon == 0.0:
            yield _sse("error", {"message": "Location is required — please select from the dropdown."}); return

        # Load Hydra config
        try:
            from ..config.loader import load_config
            from omegaconf import OmegaConf
            cfg = load_config()
            cfg = OmegaConf.merge(cfg, OmegaConf.create({
                "ollama": {"model": body.ollama_model, "base_url": body.ollama_base_url,
                           "timeout": body.ollama_timeout}
            }))
        except Exception as e:
            yield _sse("error", {"message": f"Config error: {e}"}); return

        # Emit initial steps immediately so UI shows progress
        yield _sse("step", {"agent":"System","type":"info",
            "content":f"Location: {body.location} ({body.lat:.3f}°, {body.lon:.3f}°)"})
        yield _sse("step", {"agent":"TargetAnalystAgent","type":"thought",
            "content":f"Resolving target '{body.target}' and parsing equipment…"})
        yield _sse("step", {"agent":"PlanBuilderAgent","type":"thought",
            "content":"Fetching 7-night weather forecast and scoring observing windows…"})
        yield _sse("step", {"agent":"CriticAgent","type":"thought",
            "content":"Preparing adversarial critique checks…"})

        # Run agents — synchronous, no threads, no queues, no async complexity
        try:
            from ..agents.graph import run_agent
            state = run_agent(
                target_query=body.target, location_query=body.location,
                equipment_query=body.equipment, date_preference=body.date_preference,
                lat=body.lat, lon=body.lon, timezone_offset=body.timezone_offset,
                ollama_model=body.ollama_model, ollama_base_url=body.ollama_base_url,
                ollama_timeout=body.ollama_timeout,
                session_id=body.session_id, cfg=cfg,
            )
        except Exception as e:
            log.exception("Agent run error")
            yield _sse("error", {"message": str(e)})
            yield _sse("done", {})
            return

        # Emit what each agent found
        yield from _emit_progress_sync(state)

        if state.get("error"):
            yield _sse("error", {"message": state["error"]})
        else:
            safe = _serialise(state)
            _sessions[body.session_id] = {"session_id": body.session_id, "result": safe}
            yield _sse("result", safe)

        yield _sse("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no","Connection":"keep-alive"})


def _emit_progress_sync(state: dict) -> Iterator[str]:
    """Emit what each agent produced, after the run completes."""
    if state.get("target_info"):
        ti = state["target_info"]
        yield _sse("step", {"agent":"TargetAnalystAgent","type":"observation",
           "content":f"Resolved: {ti['name']} ({ti['object_type']}, mag {ti.get('magnitude','?')}, {ti.get('angular_size_arcmin','?')} arcmin)"})

    if state.get("equipment_profile"):
        ep = state["equipment_profile"]
        name = ep.get("preset_name") or f"{ep['aperture_mm']:.0f}mm f/{ep['focal_ratio']} {ep['mount_type']}"
        yield _sse("step", {"agent":"TargetAnalystAgent","type":"observation",
           "content":f"Equipment: {name} — max sub {ep.get('max_recommended_sub_sec','?')}s"})

    if state.get("night_windows"):
        wins = state["night_windows"]
        best_s = max((w.get("overall_score",0) for w in wins), default=0)
        best_d = next((w["date"] for w in wins if w.get("overall_score",0)==best_s), "?")
        yield _sse("step", {"agent":"PlanBuilderAgent","type":"observation",
           "content":f"Scored {len(wins)} nights — best: {best_d} ({best_s}/10)"})

    if state.get("critique_result"):
        cr = state["critique_result"]
        yield _sse("step", {"agent":"CriticAgent","type":"critique","content":cr.get("critique_summary","")})
        for issue in cr.get("issues",[]):
            yield _sse("step", {"agent":"CriticAgent","type":"issue","content":issue})


def _serialise(state: dict) -> dict:
    skip = {"cfg"}
    out = {}
    for k, v in state.items():
        if k in skip: continue
        try:
            json.dumps(v); out[k] = v
        except (TypeError, ValueError):
            out[k] = str(v)
    return out


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
