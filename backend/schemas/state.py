"""LangGraph AstroState TypedDict — shared state flowing between all agent nodes."""
from __future__ import annotations
from typing import Optional, Any
from typing_extensions import TypedDict
from backend.schemas.astro import (
    EquipmentProfile, CatalogueObject, ObservationPlan, NightScore
)


class AstroState(TypedDict, total=False):
    # Input
    lat: float
    lon: float
    target_id: str
    equipment_preset: str
    equipment_raw: str
    model: str
    ollama_timeout: int

    # Resolved by TargetAnalystAgent
    target: Optional[CatalogueObject]
    equipment: Optional[EquipmentProfile]

    # Built by PlanBuilderAgent
    night_scores: list[NightScore]
    best_night: Optional[NightScore]
    backup_night: Optional[NightScore]
    plan: Optional[ObservationPlan]

    # Critic loop control
    critique_loops: int
    critic_warnings: list[str]
    critic_passed: bool

    # SSE progress streaming
    progress_events: list[dict[str, Any]]

    # Error
    error: Optional[str]
