"""All Pydantic schemas. Every LLM output is validated here."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class TargetInfo(BaseModel):
    name: str
    object_type: str = "other"
    ra_deg: float = 0.0
    dec_deg: float = 0.0
    magnitude: Optional[float] = None
    angular_size_arcmin: Optional[float] = None
    recommended_focal_length_mm: Optional[str] = None
    notes: str = ""
    resolved: bool = True

    @field_validator("object_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"galaxy","nebula","cluster","planet","double_star","moon","other"}
        return v if v in allowed else "other"


class NightWindow(BaseModel):
    date: str
    start_utc: str
    end_utc: str
    duration_hours: float
    target_max_altitude_deg: float
    moon_illumination_pct: float
    moon_rise_utc: Optional[str] = None
    moon_set_utc: Optional[str] = None
    cloud_cover_pct: float
    seeing_score: int = Field(ge=1, le=5)
    transparency_score: int = Field(ge=1, le=5)
    overall_score: float = Field(ge=0, le=10)
    limiting_factor: str = "none"


class EquipmentProfile(BaseModel):
    aperture_mm: float
    focal_length_mm: float
    focal_ratio: float
    sensor_type: str = "dslr"
    mount_type: str = "eq_goto"
    has_tracking: bool = True
    max_recommended_sub_sec: int = 120
    fov_width_deg: Optional[float] = None
    fov_height_deg: Optional[float] = None
    # UI preset info
    preset_name: Optional[str] = None
    category: Optional[str] = None  # professional | casual | mobile


class ImagingPlan(BaseModel):
    target: TargetInfo
    best_window: NightWindow
    backup_window: Optional[NightWindow] = None
    equipment: EquipmentProfile
    recommended_iso: Optional[int] = None
    recommended_gain: Optional[int] = None
    recommended_sub_seconds: int
    recommended_sub_count: int
    total_integration_minutes: float
    filter_recommendation: str
    framing_notes: str
    cardinal_direction: str
    transit_time_utc: str
    setup_time_utc: str
    dew_risk: str = "low"
    dew_heater_recommended: bool = False
    reasoning_summary: str


class CritiqueResult(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    revised_constraints: dict = Field(default_factory=dict)
    critique_summary: str


class MoonInfo(BaseModel):
    illumination_pct: float
    phase_name: str
    rise_utc: Optional[str] = None
    set_utc: Optional[str] = None
    separation_from_target_deg: Optional[float] = None
    is_problematic: bool = False
