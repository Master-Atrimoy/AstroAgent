"""All Pydantic domain schemas for DeepSkyAgent."""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field


# ── Equipment ──────────────────────────────────────────────────────────────

class EquipmentProfile(BaseModel):
    raw_input: str = ""
    preset: Optional[str] = None           # pro | casual | mobile | custom

    # Optics
    scope_name: str = "Unknown"
    aperture_mm: float = 150.0
    focal_length_mm: float = 750.0
    scope_type: str = "reflector"          # refractor | reflector | sct | rc | mak

    # Camera / sensor
    camera_name: str = "DSLR"
    sensor_w_mm: float = 22.3
    sensor_h_mm: float = 14.9
    pixel_size_um: float = 4.3
    is_dedicated_astro_cam: bool = False

    # Mount
    mount_name: str = "EQ"
    mount_type: str = "eq"                 # alt | eq | goto | none
    max_unguided_sub_sec: int = 60
    has_guiding: bool = False

    # Derived (computed after resolution)
    fov_w_deg: float = 0.0
    fov_h_deg: float = 0.0
    plate_scale_arcsec_px: float = 0.0
    limiting_magnitude: float = 13.0

    # Metadata
    resolved_by: str = "preset"           # preset | llm | user


EQUIPMENT_PRESETS: dict[str, EquipmentProfile] = {
    "pro": EquipmentProfile(
        preset="pro", scope_name="8\" SCT / RC", aperture_mm=203,
        focal_length_mm=2000, scope_type="sct",
        camera_name="Dedicated astro cam", sensor_w_mm=23.4, sensor_h_mm=15.6,
        pixel_size_um=3.76, is_dedicated_astro_cam=True,
        mount_name="EQ6-R Pro", mount_type="goto", max_unguided_sub_sec=300,
        has_guiding=True, limiting_magnitude=15.5,
        resolved_by="preset",
    ),
    "casual": EquipmentProfile(
        preset="casual", scope_name="6\" Reflector / 80mm Refractor",
        aperture_mm=150, focal_length_mm=750, scope_type="reflector",
        camera_name="DSLR (APS-C)", sensor_w_mm=22.3, sensor_h_mm=14.9,
        pixel_size_um=4.3, is_dedicated_astro_cam=False,
        mount_name="EQ5 / HEQ5", mount_type="eq", max_unguided_sub_sec=90,
        has_guiding=False, limiting_magnitude=13.5,
        resolved_by="preset",
    ),
    "mobile": EquipmentProfile(
        preset="mobile", scope_name="Smartphone / Binoculars",
        aperture_mm=50, focal_length_mm=200, scope_type="refractor",
        camera_name="Smartphone", sensor_w_mm=6.4, sensor_h_mm=4.8,
        pixel_size_um=1.4, is_dedicated_astro_cam=False,
        mount_name="None / Alt-Az", mount_type="alt", max_unguided_sub_sec=4,
        has_guiding=False, limiting_magnitude=10.5,
        resolved_by="preset",
    ),
}


# ── Catalogue objects ──────────────────────────────────────────────────────

class CatalogueObject(BaseModel):
    id: str
    name: str
    aliases: list[str] = []
    category: Literal[
        "planet", "galaxy", "nebula", "cluster_open",
        "cluster_globular", "double_star", "milky_way",
        "comet", "asteroid", "variable_star"
    ]
    ra_deg: float
    dec_deg: float
    magnitude: float
    angular_size_arcmin: float = 0.0
    constellation: str = ""
    description: str = ""
    imaging_notes: str = ""
    min_aperture_mm: int = 60
    source: str = "fallback"              # fallback | vizier | ephem | jpl


class ScoredObject(CatalogueObject):
    altitude_deg: float = 0.0
    azimuth_deg: float = 0.0
    score: int = 0
    score_components: dict = {}
    best_time_utc: str = ""


# ── Weather / conditions ───────────────────────────────────────────────────

class HourlyConditions(BaseModel):
    time_utc: str
    cloud_cover_pct: float
    precipitation_mm: float
    temperature_c: float
    dew_point_c: float
    wind_speed_ms: float
    seeing_estimate: float    # 1–5 derived
    transparency_estimate: float  # 1–5 derived


class NightScore(BaseModel):
    date: str                 # YYYY-MM-DD
    overall_score: float      # 0–100
    cloud_score: float
    seeing_score: float
    transparency_score: float
    altitude_score: float
    moon_penalty: float
    moon_illumination_pct: float
    moon_rises: Optional[str] = None
    moon_sets: Optional[str] = None
    best_window_start: str = ""
    best_window_end: str = ""
    hours: list[HourlyConditions] = []


# ── Plan / output ──────────────────────────────────────────────────────────

class ObservationPlan(BaseModel):
    target: CatalogueObject
    equipment: EquipmentProfile
    best_night: NightScore
    backup_night: Optional[NightScore] = None
    recommended_iso: int = 800
    recommended_sub_sec: int = 60
    recommended_filter: str = "None"
    dew_risk: bool = False
    narrative: str = ""
    critic_warnings: list[str] = []
    critique_loops: int = 0
    generated_at: str = ""


# ── Requests ───────────────────────────────────────────────────────────────

class LocationResult(BaseModel):
    name: str
    country: str
    lat: float
    lon: float
    display: str


class RightNowRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    equipment_preset: str = Field("casual", description="pro | casual | mobile")
    equipment_raw: str = Field("", description="Free-text equipment description")
    target_id: Optional[str] = None
    model: str = "llama3.2"


class PlanAheadRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    target_id: str
    equipment_preset: str = "casual"
    equipment_raw: str = ""
    model: str = "llama3.2"
    ollama_timeout: int = 60
