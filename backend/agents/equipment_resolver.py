"""
EquipmentResolverAgent — identifies telescope, camera, and mount from free text.
Falls back to preset if LLM fails or times out.
"""
from __future__ import annotations
import logging
import os
from backend.schemas.astro import EquipmentProfile, EQUIPMENT_PRESETS
from backend.agents.llm import call_llm, parse_json_output
from backend.config.loader import get_config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert astronomy equipment database.
Given a description of astronomical equipment, extract and return ONLY a JSON object.
If the model/make is recognised, use its real specs. If not, make reasonable estimates.
Return EXACTLY this JSON schema with no other text:
{
  "scope_name": "string",
  "aperture_mm": number,
  "focal_length_mm": number,
  "scope_type": "refractor|reflector|sct|rc|mak",
  "camera_name": "string",
  "sensor_w_mm": number,
  "sensor_h_mm": number,
  "pixel_size_um": number,
  "is_dedicated_astro_cam": boolean,
  "mount_name": "string",
  "mount_type": "alt|eq|goto|none",
  "max_unguided_sub_sec": number,
  "has_guiding": boolean
}"""


def resolve_equipment(
    raw_input: str,
    preset: str = "casual",
    model: str = "llama3.2",
    timeout: int = 30,
) -> EquipmentProfile:
    """
    Resolve equipment from free text via LLM.
    Falls back to preset on any failure.
    """
    cfg = get_config()
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # If no free text, just use preset — no LLM call at all
    if not raw_input.strip():
        base = EQUIPMENT_PRESETS.get(preset, EQUIPMENT_PRESETS["casual"])
        profile = base.model_copy()
        profile.raw_input = raw_input
        return profile

    prompt = f"""Identify the astronomical equipment from this description and return the JSON:

Equipment description: "{raw_input}"

Common examples for reference:
- "Celestron NexStar 8SE" → aperture 203mm, focal 2032mm, SCT, alt-az goto, max sub 60s
- "Sky-Watcher 150PL" → aperture 150mm, focal 1200mm, reflector, EQ, max sub 90s
- "William Optics GT81" → aperture 81mm, focal 478mm, refractor, EQ, max sub 120s
- "ZWO ASI294MC Pro" → dedicated astro cam, sensor 19.1x13.0mm, pixel 4.63um
- "Canon EOS R" → DSLR, sensor 35.9x23.9mm, pixel 5.36um
- "EQ6-R Pro" → goto EQ mount, max unguided 300s, has guiding capability

Return ONLY the JSON object."""

    try:
        raw = call_llm(
            prompt=prompt,
            model=model,
            system=SYSTEM_PROMPT,
            ollama_url=ollama_url,
            timeout=timeout,
        )
        data = parse_json_output(raw)

        # Derive FOV and plate scale
        aperture = float(data.get("aperture_mm", 150))
        focal = float(data.get("focal_length_mm", 750))
        sensor_w = float(data.get("sensor_w_mm", 22.3))
        sensor_h = float(data.get("sensor_h_mm", 14.9))
        pixel_um = float(data.get("pixel_size_um", 4.3))

        fov_w = (sensor_w / focal) * (180 / 3.14159) if focal > 0 else 1.0
        fov_h = (sensor_h / focal) * (180 / 3.14159) if focal > 0 else 0.7
        plate_scale = (pixel_um / 1000 / focal) * 206265 if focal > 0 else 2.9

        import math
        lim_mag = round(2.1 + 5 * math.log10(max(1, aperture)), 1)

        return EquipmentProfile(
            raw_input=raw_input,
            preset=preset,
            scope_name=data.get("scope_name", "Unknown scope"),
            aperture_mm=aperture,
            focal_length_mm=focal,
            scope_type=data.get("scope_type", "reflector"),
            camera_name=data.get("camera_name", "Unknown camera"),
            sensor_w_mm=sensor_w,
            sensor_h_mm=sensor_h,
            pixel_size_um=pixel_um,
            is_dedicated_astro_cam=bool(data.get("is_dedicated_astro_cam", False)),
            mount_name=data.get("mount_name", "Unknown mount"),
            mount_type=data.get("mount_type", "eq"),
            max_unguided_sub_sec=int(data.get("max_unguided_sub_sec", 60)),
            has_guiding=bool(data.get("has_guiding", False)),
            fov_w_deg=round(fov_w, 3),
            fov_h_deg=round(fov_h, 3),
            plate_scale_arcsec_px=round(plate_scale, 2),
            limiting_magnitude=lim_mag,
            resolved_by="llm",
        )

    except Exception as e:
        log.warning(f"Equipment LLM resolution failed ({e}), falling back to preset '{preset}'")
        base = EQUIPMENT_PRESETS.get(preset, EQUIPMENT_PRESETS["casual"])
        profile = base.model_copy()
        profile.raw_input = raw_input
        profile.resolved_by = "preset_fallback"
        return profile
