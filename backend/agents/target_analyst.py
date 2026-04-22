"""Agent 1 — TargetAnalystAgent."""
from __future__ import annotations
import logging
import math
import re
from typing import Any

log = logging.getLogger("astroagent.target")

# Equipment presets — these match the UI dropdown
EQUIPMENT_PRESETS: dict[str, dict] = {
    # ── Professional ────────────────────────────────────────────────────────
    "pro_sct8":      dict(aperture_mm=203.2, focal_length_mm=2032, focal_ratio=10.0,
                          sensor_type="dedicated_astro", mount_type="eq_goto",
                          has_tracking=True, max_recommended_sub_sec=300,
                          preset_name="8\" SCT + Dedicated Astro Camera", category="professional"),
    "pro_newt10":    dict(aperture_mm=254.0, focal_length_mm=1270, focal_ratio=5.0,
                          sensor_type="dedicated_astro", mount_type="eq_goto",
                          has_tracking=True, max_recommended_sub_sec=300,
                          preset_name="10\" Newtonian + ZWO/QHY Camera", category="professional"),
    "pro_refract5":  dict(aperture_mm=130.0, focal_length_mm=910,  focal_ratio=7.0,
                          sensor_type="dedicated_astro", mount_type="eq_goto",
                          has_tracking=True, max_recommended_sub_sec=300,
                          preset_name="5\" APO Refractor + Mono Camera", category="professional"),
    # ── Casual ──────────────────────────────────────────────────────────────
    "cas_dslr8sct":  dict(aperture_mm=203.2, focal_length_mm=2032, focal_ratio=10.0,
                          sensor_type="dslr", mount_type="eq_goto",
                          has_tracking=True, max_recommended_sub_sec=300,
                          preset_name="8\" SCT + DSLR (Canon/Nikon)", category="casual"),
    "cas_newt6":     dict(aperture_mm=152.4, focal_length_mm=762,  focal_ratio=5.0,
                          sensor_type="dslr", mount_type="eq_goto",
                          has_tracking=True, max_recommended_sub_sec=300,
                          preset_name="6\" Newtonian + DSLR on EQ Mount", category="casual"),
    "cas_dob10":     dict(aperture_mm=254.0, focal_length_mm=1200, focal_ratio=4.7,
                          sensor_type="dslr", mount_type="dobsonian",
                          has_tracking=False, max_recommended_sub_sec=5,
                          preset_name="10\" Dobsonian + DSLR (visual priority)", category="casual"),
    "cas_80ref":     dict(aperture_mm=80.0,  focal_length_mm=480,  focal_ratio=6.0,
                          sensor_type="dslr", mount_type="eq_manual",
                          has_tracking=True, max_recommended_sub_sec=60,
                          preset_name="80mm Refractor + DSLR on Manual EQ", category="casual"),
    # ── Mobile ──────────────────────────────────────────────────────────────
    "mob_iphone":    dict(aperture_mm=12.0,  focal_length_mm=26,   focal_ratio=2.0,
                          sensor_type="mobile", mount_type="alt_az",
                          has_tracking=False, max_recommended_sub_sec=4,
                          preset_name="iPhone / Android + NightCap / ProShot", category="mobile"),
    "mob_scope_phone": dict(aperture_mm=70.0, focal_length_mm=400,  focal_ratio=5.7,
                             sensor_type="mobile", mount_type="alt_az",
                             has_tracking=False, max_recommended_sub_sec=4,
                             preset_name="Telescope Eyepiece + Smartphone Adapter", category="mobile"),
    "mob_binoculars": dict(aperture_mm=50.0, focal_length_mm=250,  focal_ratio=5.0,
                            sensor_type="mobile", mount_type="alt_az",
                            has_tracking=False, max_recommended_sub_sec=2,
                            preset_name="Binoculars + Phone Clamp", category="mobile"),
}


def run_target_analyst(state: dict, cfg: Any) -> dict:
    from ..schemas.astro import TargetInfo, EquipmentProfile
    from ..tools.horizons import resolve_target
    from datetime import datetime

    lat, lon = state["lat"], state["lon"]
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    # Resolve target
    raw = resolve_target(state["target_query"], lat, lon, date_str)
    target = TargetInfo(**raw)

    # Equipment — check if it's a preset key first
    eq_query = state["equipment_query"].strip()
    if eq_query in EQUIPMENT_PRESETS:
        ep = EquipmentProfile(**EQUIPMENT_PRESETS[eq_query])
    else:
        # Try LLM parse with timeout, fall back to rule-based
        ep = _parse_equipment_with_llm(
            eq_query, state["ollama_model"], state["ollama_base_url"],
            state.get("ollama_timeout", 60)
        )

    ep = _add_fov(ep)

    updates = {
        "target_info":      target.model_dump(),
        "equipment_profile": ep.model_dump(),
    }
    if not target.resolved:
        updates["error"] = target.notes

    return {**state, **updates}


def _parse_equipment_with_llm(query: str, model: str, base_url: str, timeout: int):
    from ..schemas.astro import EquipmentProfile
    from .llm import call_llm, parse_json_output

    PROMPT = f"""Parse this telescope/camera equipment into JSON.
Equipment: "{query}"

Return ONLY valid JSON:
{{
  "aperture_mm": <float mm, 8-inch=203.2>,
  "focal_length_mm": <float>,
  "focal_ratio": <float e.g. 10.0>,
  "sensor_type": <"dslr"|"mirrorless"|"dedicated_astro"|"mobile"|"visual">,
  "mount_type": <"eq_goto"|"eq_manual"|"alt_az"|"dobsonian"|"unknown">,
  "has_tracking": <true|false>,
  "max_recommended_sub_sec": <int: eq_goto=300, eq_manual=60, alt_az=30, dobsonian=5, mobile=4>
}}
Rules: SCT=f/10, Newtonian=f/5, refractor=f/7. focal_length=aperture*ratio.
Goto/computerised mounts have tracking. Dobsonian has no tracking."""

    try:
        raw = call_llm(PROMPT, model, base_url, timeout=timeout)
        return parse_json_output(raw, EquipmentProfile)
    except Exception as e:
        log.warning("LLM equipment parse failed (%s): %s — using rule fallback", type(e).__name__, e)
        return _rule_parse(query)


def _rule_parse(query: str):
    from ..schemas.astro import EquipmentProfile
    q = query.lower()
    ap, focal, ratio = 150.0, 750.0, 5.0
    mount, tracking, sensor = "eq_goto", True, "dslr"

    # Aperture
    inch = re.search(r'(\d+\.?\d*)\s*["-]?\s*inch', q)
    mm   = (re.search(r'(\d{2,4})\s*mm\s*(?:aperture|mirror|lens|refract|newt|scope)', q)
            or re.search(r'\b(\d{2,4})\s*mm\b', q))
    fr   = re.search(r'f[/\s]?(\d+\.?\d*)', q)

    if inch:   ap = round(float(inch.group(1)) * 25.4, 1)
    elif mm:   ap = float(mm.group(1))

    # Try to infer focal ratio from scope type
    if "sct" in q or "cassegrain" in q:
        ratio = 10.0
    elif "newt" in q or "reflector" in q:
        ratio = 5.0
    elif "refract" in q or "apo" in q:
        ratio = 7.0

    if fr: ratio = float(fr.group(1))
    focal = round(ap * ratio)

    if any(x in q for x in ["goto","computeris","eq6","heq5","avx","atlas","synscan"]):
        mount, tracking = "eq_goto", True
    elif "dobsonian" in q or " dob" in q:
        mount, tracking = "dobsonian", False
    elif "alt-az" in q or "altaz" in q:
        mount, tracking = "alt_az", True
    elif "manual" in q:
        mount, tracking = "eq_manual", True
    elif "phone" in q or "mobile" in q or "iphone" in q or "android" in q:
        mount, tracking = "alt_az", False; sensor = "mobile"

    if any(x in q for x in ["asi","zwo","qhy","atik","dedicated","mono","colour cam"]):
        sensor = "dedicated_astro"
    elif "mirrorless" in q or "sony a" in q or "fuji" in q:
        sensor = "mirrorless"
    elif "phone" in q or "mobile" in q or "iphone" in q:
        sensor = "mobile"

    max_sub = {"eq_goto":300,"eq_manual":60,"alt_az":30,"dobsonian":5,"unknown":60}.get(mount,60)
    if sensor == "mobile": max_sub = 4

    return EquipmentProfile(
        aperture_mm=ap, focal_length_mm=float(focal), focal_ratio=ratio,
        sensor_type=sensor, mount_type=mount, has_tracking=tracking,
        max_recommended_sub_sec=max_sub,
    )


def _add_fov(ep) -> "EquipmentProfile":
    SENSOR_MM = {
        "dslr": (22.3, 14.9), "mirrorless": (23.5, 15.6),
        "dedicated_astro": (17.6, 13.5), "mobile": (6.4, 4.8),
    }
    if ep.sensor_type in SENSOR_MM and ep.focal_length_mm > 0:
        w, h = SENSOR_MM[ep.sensor_type]
        import math
        ep.fov_width_deg  = round(math.degrees(2*math.atan(w/(2*ep.focal_length_mm))), 2)
        ep.fov_height_deg = round(math.degrees(2*math.atan(h/(2*ep.focal_length_mm))), 2)
    return ep
