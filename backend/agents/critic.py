"""
CriticAgent — LangGraph node.
Deterministic checks first (always correct), then optional LLM critique.
If issues found → signals loop back to PlanBuilder.
"""
from __future__ import annotations
import os
import logging
from backend.schemas.state import AstroState
from backend.agents.llm import call_llm
from backend.config.loader import get_config

log = logging.getLogger(__name__)


def _deterministic_checks(state: AstroState, cfg) -> list[str]:
    """Run hard rule checks. Returns list of warning strings."""
    warnings = []
    plan = state.get("plan")
    equipment = state.get("equipment")
    best = state.get("best_night")

    if not plan or not equipment or not best:
        return ["Plan incomplete — cannot run critic checks"]

    c = cfg.agent.critic

    # 1. Moon illumination
    if best.moon_illumination_pct > c.moon_illumination_max_pct:
        warnings.append(
            f"Moon is {best.moon_illumination_pct:.0f}% illuminated "
            f"(threshold: {c.moon_illumination_max_pct}%). Consider narrowband filters."
        )

    # 2. Moon rises mid-session
    if best.moon_rises and best.best_window_start:
        try:
            rise_h = int(best.moon_rises[11:13]) if len(best.moon_rises) > 13 else 0
            window_h = int(best.best_window_start[11:13]) if len(best.best_window_start) > 13 else 20
            if window_h <= rise_h <= window_h + 3:
                warnings.append(
                    f"Moon rises at {best.moon_rises} — mid-session interference likely."
                )
        except Exception:
            pass

    # 3. Sub-exposure vs mount limit
    if plan.recommended_sub_sec > equipment.max_unguided_sub_sec and not equipment.has_guiding:
        warnings.append(
            f"Recommended sub ({plan.recommended_sub_sec}s) exceeds mount's "
            f"unguided limit ({equipment.max_unguided_sub_sec}s). "
            f"Reduce to {equipment.max_unguided_sub_sec}s or add guiding."
        )

    # 4. Target below min altitude
    if best.altitude_score < 20:
        warnings.append(
            f"Target altitude score is low ({best.altitude_score:.0f}/100). "
            f"Consider waiting for target to rise or choosing a backup."
        )

    # 5. Dew risk
    if plan.dew_risk:
        warnings.append(
            "Dew risk detected — temperature near dew point. "
            "Use a dew heater or dew shield."
        )

    # 6. Integration time vs window
    if best.best_window_start and best.best_window_end:
        try:
            # Rough window duration estimate
            sh = int(best.best_window_start[11:13]) if len(best.best_window_start) > 13 else 21
            eh = int(best.best_window_end[11:13]) if len(best.best_window_end) > 13 else 3
            window_min = ((eh - sh + 24) % 24) * 60
            # Assume 100 subs as a proxy for integration demand
            integration_min = (plan.recommended_sub_sec * 100) / 60
            fraction = integration_min / max(1, window_min)
            if fraction > c.max_sub_fraction_of_window:
                warnings.append(
                    f"Planned integration ({integration_min:.0f} min) may exceed "
                    f"clear window ({window_min:.0f} min). Reduce sub count or sub length."
                )
        except Exception:
            pass

    return warnings


def critic_node(state: AstroState) -> AstroState:
    """Node 3: run checks, decide whether to loop or pass."""
    if state.get("error"):
        return state

    cfg = get_config()
    events = list(state.get("progress_events", []))
    loops = state.get("critique_loops", 0)
    max_loops = cfg.agent.critic.max_critique_loops

    events.append({"agent": "Critic", "status": "running",
                   "message": f"Running adversarial checks (loop {loops + 1}/{max_loops + 1})…"})

    warnings = _deterministic_checks(state, cfg)

    # Optional LLM critique (only on first loop, if issues found)
    if warnings and loops == 0:
        try:
            ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            plan = state.get("plan")
            target = state.get("target")
            prompt = f"""You are a critical astrophotography expert reviewing this plan.
Target: {target.name if target else 'Unknown'}
Issues found: {'; '.join(warnings)}
Plan ISO: {plan.recommended_iso if plan else '?'}, Sub: {plan.recommended_sub_sec if plan else '?'}s

In 1-2 sentences, what is the single most important issue and how should it be fixed?
Be direct and specific."""
            llm_critique = call_llm(
                prompt, model=state.get("model", "llama3.2"),
                ollama_url=ollama_url, timeout=20
            )
            warnings.append(f"[AI Critique] {llm_critique}")
        except Exception as e:
            log.warning(f"LLM critique skipped: {e}")

    # Update plan with warnings
    plan = state.get("plan")
    if plan:
        plan.critic_warnings = warnings
        plan.critique_loops = loops + 1

    passed = len([w for w in warnings if "[AI Critique]" not in w]) == 0

    if passed:
        events.append({"agent": "Critic", "status": "done",
                       "message": "All checks passed ✓"})
    else:
        if loops < max_loops:
            events.append({"agent": "Critic", "status": "warning",
                           "message": f"{len(warnings)} issue(s) found — requesting plan revision…"})
        else:
            events.append({"agent": "Critic", "status": "done",
                           "message": f"Max loops reached. {len(warnings)} warning(s) noted."})

    return {
        **state,
        "plan": plan,
        "critic_warnings": warnings,
        "critic_passed": passed or loops >= max_loops,
        "critique_loops": loops + 1,
        "progress_events": events,
    }


def should_loop(state: AstroState) -> str:
    """LangGraph conditional edge: loop back or finish."""
    cfg = get_config()
    if state.get("critic_passed", False):
        return "finish"
    if state.get("critique_loops", 0) >= cfg.agent.critic.max_critique_loops:
        return "finish"
    return "replan"
