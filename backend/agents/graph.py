"""
DeepSkyAgent — LangGraph StateGraph
Nodes: TargetAnalyst → PlanBuilder → Critic → (loop or finish)
"""
from __future__ import annotations
from langgraph.graph import StateGraph, END
from backend.schemas.state import AstroState
from backend.agents.target_analyst import target_analyst_node
from backend.agents.plan_builder import plan_builder_node
from backend.agents.critic import critic_node, should_loop

# ── Build graph ────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(AstroState)

    graph.add_node("target_analyst", target_analyst_node)
    graph.add_node("plan_builder",   plan_builder_node)
    graph.add_node("critic",         critic_node)

    graph.set_entry_point("target_analyst")

    graph.add_edge("target_analyst", "plan_builder")
    graph.add_edge("plan_builder",   "critic")

    # Conditional: critic passes → END, fails → replan (back to plan_builder)
    graph.add_conditional_edges(
        "critic",
        should_loop,
        {
            "finish": END,
            "replan": "plan_builder",
        },
    )

    return graph.compile()


# Singleton compiled graph
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
