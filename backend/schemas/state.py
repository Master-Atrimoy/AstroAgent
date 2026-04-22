from __future__ import annotations
from typing import TypedDict, Optional, Annotated, Any
import operator


class AstroState(TypedDict):
    # Request
    target_query: str
    location_query: str
    equipment_query: str
    date_preference: str
    lat: float
    lon: float
    timezone_offset: int

    # Progressive outputs
    target_info: Optional[dict]
    equipment_profile: Optional[dict]
    weather_windows: list[dict]
    night_windows: list[dict]
    imaging_plan: Optional[dict]
    critique_result: Optional[dict]
    plan_approved: bool

    # Control
    messages: Annotated[list[dict], operator.add]
    critique_loop_count: int
    error: Optional[str]
    session_id: str

    # Runtime config (injected, not serialised)
    ollama_model: str
    ollama_base_url: str
    ollama_timeout: int
    cfg: Optional[Any]
