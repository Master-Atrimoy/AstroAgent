"""
TargetAnalystAgent — LangGraph node.
Resolves target from catalogue + validates equipment.
"""
from __future__ import annotations
import logging
from backend.schemas.state import AstroState
from backend.tools.catalogue import get_catalogue
from backend.agents.equipment_resolver import resolve_equipment

log = logging.getLogger(__name__)


def target_analyst_node(state: AstroState) -> AstroState:
    """Node 1: resolve target object and equipment profile."""
    events = list(state.get("progress_events", []))
    events.append({"agent": "TargetAnalyst", "status": "running",
                   "message": "Resolving target and equipment…"})

    # Resolve target from catalogue
    target_id = state.get("target_id", "")
    catalogue = get_catalogue()
    target = next((o for o in catalogue if o.id == target_id), None)

    if target is None:
        events.append({"agent": "TargetAnalyst", "status": "error",
                       "message": f"Target '{target_id}' not found in catalogue"})
        return {**state, "error": f"Target '{target_id}' not found", "progress_events": events}

    # Resolve equipment
    equipment = resolve_equipment(
        raw_input=state.get("equipment_raw", ""),
        preset=state.get("equipment_preset", "casual"),
        model=state.get("model", "llama3.2"),
        timeout=30,
    )

    events.append({"agent": "TargetAnalyst", "status": "done",
                   "message": f"Target: {target.name} | Equipment: {equipment.scope_name} + {equipment.camera_name}"})

    return {
        **state,
        "target": target,
        "equipment": equipment,
        "progress_events": events,
        "critic_warnings": [],
        "critique_loops": 0,
    }
