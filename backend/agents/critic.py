"""Agent 3 — CriticAgent. Deterministic + LLM adversarial critique."""
from __future__ import annotations
import logging
from typing import Any

log = logging.getLogger("astroagent.critic")

_CRITIC_PROMPT = """You are a critical astrophotography expert. Find REAL specific problems with this plan.

TARGET: {name} ({type}, mag {mag})
WINDOW: {date} {start}-{end} UTC ({hours}h), cloud {cloud}%, seeing {see}/5
MOON: {moon_pct}% illum, rises {moon_rise}, sets {moon_set}
EQUIPMENT: {ap}mm f/{fr} {mount}, max sub {max_sub}s
PLAN: {sub_s}s x {sub_n} subs = {total_min}min, filter={filter}, dew={dew}

Critic thresholds: moon_illum_max={moon_max}%, moon_sep_min={sep_min}°, dew_margin={dew_margin}°C

Check:
1. Moon rises mid-session and contaminates it?
2. Sub-exposure exceeds mount tracking limit?
3. Integration time exceeds 85% of window duration?
4. Filter choice appropriate for moon illumination + target type?
5. Dew risk without heater on clear night?
6. Any other domain-specific issues?

Return ONLY:
{{"approved": <true/false>, "issues": ["<specific issue>"], "revised_constraints": {{}}, "critique_summary": "<one sentence>"}}
If approved: issues=[]"""


def run_critic(state: dict, cfg: Any) -> dict:
    from ..schemas.astro import ImagingPlan, CritiqueResult

    plan_dict = state.get("imaging_plan")
    if not plan_dict:
        return {**state, "critique_result": None, "plan_approved": False,
                "error": "No imaging plan to critique."}

    try:
        plan = ImagingPlan(**plan_dict)
    except Exception as e:
        return {**state, "critique_result": None, "plan_approved": False,
                "error": f"Plan schema error: {e}"}

    ccfg = cfg.agent.critic

    # Deterministic checks first (always run, no LLM)
    det_issues = _deterministic_checks(plan, ccfg)

    # LLM critique (slim payload, explicit timeout, never crashes)
    llm_result = _llm_critique(plan, ccfg, state)

    all_issues = det_issues + llm_result.issues
    approved   = len(all_issues) == 0 and llm_result.approved

    result = CritiqueResult(
        approved=approved,
        issues=all_issues,
        revised_constraints=llm_result.revised_constraints,
        critique_summary=(
            f"✓ Plan approved. {llm_result.critique_summary}"
            if approved else
            f"✗ {len(all_issues)} issue(s). {llm_result.critique_summary}"
        ),
    )
    return {
        **state,
        "critique_result":   result.model_dump(),
        "plan_approved":     approved,
        "critique_loop_count": state.get("critique_loop_count", 0) + 1,
    }


def _deterministic_checks(plan, ccfg) -> list[str]:
    """Hard rules — no LLM, always reliable."""
    issues = []
    w  = plan.best_window
    eq = plan.equipment

    # 1. Moon illumination
    if w.moon_illumination_pct > float(ccfg.moon_illumination_max_pct):
        issues.append(
            f"Moon is {w.moon_illumination_pct:.0f}% illuminated (threshold {ccfg.moon_illumination_max_pct}%). "
            "Switch to narrowband filter for nebulae, or choose a darker night."
        )

    # 2. Moon rises mid-session
    if w.moon_rise_utc:
        s = _to_mins(w.start_utc)
        e = _to_mins(w.end_utc)
        mr = _to_mins(w.moon_rise_utc)
        if s < mr < e:
            contaminated = round((e - mr) / 60, 1)
            issues.append(
                f"Moon rises at {w.moon_rise_utc} UTC mid-session, contaminating the last {contaminated}h. "
                f"End session before {w.moon_rise_utc} or use narrowband filter."
            )

    # 3. Sub-exposure vs mount
    mount_max = {"eq_goto":300,"eq_manual":60,"alt_az":30,"dobsonian":5,"unknown":60}
    limit = mount_max.get(eq.mount_type, 120)
    if plan.recommended_sub_seconds > limit:
        issues.append(
            f"Sub-exposure {plan.recommended_sub_seconds}s exceeds {limit}s limit for {eq.mount_type} mount. "
            f"Stars will trail. Reduce to {limit}s."
        )

    # 4. Integration > 85% of window
    win_mins = w.duration_hours * 60
    if plan.total_integration_minutes > win_mins * 0.85:
        issues.append(
            f"Integration ({plan.total_integration_minutes:.0f}min) exceeds 85% of window ({win_mins:.0f}min). "
            f"No time for calibration frames. Reduce to {int(win_mins*0.7)}min."
        )

    # 5. Dew risk without heater
    if w.cloud_cover_pct < 30 and plan.dew_risk in ("medium","high") and not plan.dew_heater_recommended:
        issues.append(
            f"Clear night with {plan.dew_risk} dew risk but no dew heater. Optics will fog."
        )

    # 6. Target below 30°
    if w.target_max_altitude_deg < 30:
        issues.append(
            f"Target peaks at only {w.target_max_altitude_deg:.0f}°. "
            "Atmospheric dispersion will significantly degrade image quality."
        )

    return issues


def _llm_critique(plan, ccfg, state) -> "CritiqueResult":
    from ..schemas.astro import CritiqueResult
    from .llm import call_llm, parse_json_output

    try:
        w  = plan.best_window
        eq = plan.equipment
        prompt = _CRITIC_PROMPT.format(
            name=plan.target.name, type=plan.target.object_type,
            mag=plan.target.magnitude or "?",
            date=w.date, start=w.start_utc, end=w.end_utc,
            hours=w.duration_hours, cloud=w.cloud_cover_pct,
            see=w.seeing_score, moon_pct=w.moon_illumination_pct,
            moon_rise=w.moon_rise_utc or "before dark",
            moon_set=w.moon_set_utc or "before dark",
            ap=eq.aperture_mm, fr=eq.focal_ratio, mount=eq.mount_type,
            max_sub=eq.max_recommended_sub_sec,
            sub_s=plan.recommended_sub_seconds,
            sub_n=plan.recommended_sub_count,
            total_min=plan.total_integration_minutes,
            filter=plan.filter_recommendation,
            dew=plan.dew_risk,
            moon_max=ccfg.moon_illumination_max_pct,
            sep_min=ccfg.moon_separation_min_deg,
            dew_margin=ccfg.dew_point_margin_deg,
        )
        raw = call_llm(prompt, state["ollama_model"], state["ollama_base_url"],
                       timeout=state.get("ollama_timeout", 90))
        return parse_json_output(raw, CritiqueResult)
    except Exception as e:
        log.warning("LLM critique failed (%s): %s", type(e).__name__, e)
        return CritiqueResult(
            approved=True, issues=[], revised_constraints={},
            critique_summary=f"LLM critique unavailable ({type(e).__name__}). Deterministic checks ran."
        )


def _to_mins(hhmm: str) -> int:
    try:
        h, m = hhmm.strip().split(":")
        t = int(h)*60 + int(m)
        return t if t >= 600 else t + 1440
    except Exception:
        return 0
