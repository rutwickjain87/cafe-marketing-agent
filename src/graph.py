from langgraph.graph import StateGraph, END

from src.state import AgentState
from src.agents.coordinator import coordinator_node
from src.agents.strategy import strategy_node
from src.agents.creative import creative_node
from src.agents.publishing import publishing_node
from src.agents.analytics import analytics_node
from src.agents.engagement.engagement import engagement_node


def _route_after_creative(state: AgentState) -> str:
    """Pause for human approval if confidence is low; otherwise proceed to publish."""
    if state.get("human_review_required"):
        return END  # resume after setting approved=True externally
    return "publishing"


def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("coordinator", coordinator_node)
    g.add_node("strategy", strategy_node)
    g.add_node("creative", creative_node)
    g.add_node("publishing", publishing_node)
    g.add_node("engagement", engagement_node)
    g.add_node("analytics", analytics_node)

    g.set_entry_point("coordinator")
    g.add_edge("coordinator", "strategy")
    g.add_edge("strategy", "creative")
    g.add_conditional_edges(
        "creative",
        _route_after_creative,
        {"publishing": "publishing", END: END},
    )
    g.add_edge("publishing", "engagement")
    g.add_edge("engagement", "analytics")
    g.add_edge("analytics", END)

    return g.compile()


graph = build_graph()
