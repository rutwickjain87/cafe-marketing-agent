from __future__ import annotations

import os

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import AgentState
from src.agents.coordinator import coordinator_node
from src.agents.strategy import strategy_node
from src.agents.creative import creative_node
from src.agents.publishing import publishing_node
from src.agents.analytics import analytics_node
from src.agents.engagement.engagement import engagement_node


def _route_after_coordinator(state: AgentState) -> str:
    if state.get("human_review_required"):
        return END
    return "strategy"


def _route_after_creative(state: AgentState) -> str:
    """Pause for human approval when confidence is low or draft needs review.

    The graph halts at END with status='draft'. The operator sets approved=True
    externally and resumes by re-invoking the graph with the persisted thread_id.
    The approved invariant is then enforced in publishing_node itself.
    """
    if state.get("human_review_required"):
        return "human_approval"
    if not state.get("approved"):
        return "human_approval"
    return "publishing"


def _human_approval_node(state: AgentState) -> AgentState:
    """Interrupt point — execution pauses here until the operator resumes.

    To approve: update state["approved"] = True and state["human_review_required"] = False,
    then call graph.invoke(state, config={"configurable": {"thread_id": <id>}}).
    """
    from langgraph.types import interrupt  # lazy import — only needed at runtime
    interrupt("Awaiting human approval of creative assets.")
    return state  # unreachable; interrupt raises internally


def _route_after_approval(state: AgentState) -> str:
    if state.get("approved"):
        return "publishing"
    return END


def _make_checkpointer():
    """Return a Supabase-backed Postgres checkpointer when credentials are present,
    falling back to in-memory for local dev / CI without a Supabase project."""
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")

    if supabase_url and supabase_key:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            # Supabase exposes a Postgres connection string via the connection pooler
            db_url = os.environ.get("SUPABASE_DB_URL", "")
            if db_url:
                return PostgresSaver.from_conn_string(db_url)
        except ImportError:
            pass  # langgraph-checkpoint-postgres not installed; fall through

    return MemorySaver()


def build_graph() -> StateGraph:
    checkpointer = _make_checkpointer()
    g = StateGraph(AgentState)

    g.add_node("coordinator", coordinator_node)
    g.add_node("strategy", strategy_node)
    g.add_node("creative", creative_node)
    g.add_node("human_approval", _human_approval_node)
    g.add_node("publishing", publishing_node)
    g.add_node("engagement", engagement_node)
    g.add_node("analytics", analytics_node)

    g.set_entry_point("coordinator")

    g.add_conditional_edges(
        "coordinator",
        _route_after_coordinator,
        {"strategy": "strategy", END: END},
    )
    g.add_edge("strategy", "creative")
    g.add_conditional_edges(
        "creative",
        _route_after_creative,
        {"publishing": "publishing", "human_approval": "human_approval"},
    )
    g.add_conditional_edges(
        "human_approval",
        _route_after_approval,
        {"publishing": "publishing", END: END},
    )
    g.add_edge("publishing", "engagement")
    g.add_edge("engagement", "analytics")
    g.add_edge("analytics", END)

    return g.compile(checkpointer=checkpointer, interrupt_before=["human_approval"])


graph = build_graph()
