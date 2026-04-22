"""Agent pipeline — runs the three agents directly, no LangGraph runtime."""
from __future__ import annotations
from typing import Any
import logging

log = logging.getLogger("astroagent.graph")


def run_agent(*, target_query: str, location_query: str, equipment_query: str,
               date_preference: str, lat: float, lon: float, timezone_offset: int,
               ollama_model: str, ollama_base_url: str, ollama_timeout: int,
               session_id: str, cfg: Any) -> dict:

    state = dict(
        target_query=target_query, location_query=location_query,
        equipment_query=equipment_query, date_preference=date_preference,
        lat=lat, lon=lon, timezone_offset=timezone_offset,
        target_info=None, equipment_profile=None,
        weather_windows=[], night_windows=[], imaging_plan=None,
        critique_result=None, plan_approved=False,
        messages=[], critique_loop_count=0, error=None,
        session_id=session_id,
        ollama_model=ollama_model, ollama_base_url=ollama_base_url,
        ollama_timeout=ollama_timeout, cfg=cfg,
    )

    # Agent 1: resolve target + equipment
    try:
        from .target_analyst import run_target_analyst
        state = run_target_analyst(state, cfg)
        log.info("TargetAnalyst done. error=%s", state.get("error"))
    except Exception as e:
        log.exception("TargetAnalyst failed")
        state["error"] = str(e)
        return state

    if state.get("error"):
        return state

    # Agent 2 + 3: plan builder → critic loop (matches original LangGraph logic)
    max_loops = int(cfg.agent.critic.max_critique_loops)
    for loop in range(max_loops):
        try:
            from .plan_builder import run_plan_builder
            state = run_plan_builder(state, cfg)
            log.info("PlanBuilder done. error=%s", state.get("error"))
        except Exception as e:
            log.exception("PlanBuilder failed")
            state["error"] = str(e)
            return state

        if state.get("error"):
            return state

        try:
            from .critic import run_critic
            state = run_critic(state, cfg)
            log.info("Critic done. approved=%s issues=%s",
                     state.get("plan_approved"), len((state.get("critique_result") or {}).get("issues", [])))
        except Exception as e:
            log.exception("Critic failed")
            state["error"] = str(e)
            return state

        if state.get("plan_approved"):
            break

    return state
