from __future__ import annotations

import os
from datetime import datetime, timezone

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import AgentState
from src.schemas import PostAsset
from src.agents.coordinator import coordinator_node
from src.agents.strategy import strategy_node
from src.agents.creative import creative_node
from src.agents.media import media_submit_node, media_await_node, has_pending_render
from src.agents.publishing import publishing_node
from src.agents.analytics import analytics_node
from src.agents.engagement.engagement import engagement_node
from src.memory.schedule_store import enqueue_scheduled


def _route_after_coordinator(state: AgentState) -> str:
    if state.get("human_review_required"):
        return END
    return "strategy"


def _route_after_media_submit(state: AgentState) -> str:
    """Wait on fal renders when a reel clip is still pending; else go to approval."""
    if has_pending_render(state):
        return "media_await"
    return "human_approval"


def _route_after_media_await(state: AgentState) -> str:
    """Loop back to the (interrupt-gated) await node until every clip has landed."""
    if has_pending_render(state):
        return "media_await"
    return "human_approval"


def _human_approval_node(state: AgentState) -> AgentState:
    """Pass-through checkpoint. Pausing is handled by interrupt_before=['human_approval'];
    the operator resumes by setting approved + invoking with None (see resume_run)."""
    return state


def _has_future_schedule(state: AgentState) -> bool:
    now = datetime.now(timezone.utc)
    for raw in state.get("creative_assets", []):
        asset = PostAsset.model_validate(raw)
        if asset.scheduled_at and asset.scheduled_at > now:
            return True
    return False


def _route_after_approval(state: AgentState) -> str:
    if not state.get("approved"):
        return END
    if _has_future_schedule(state):
        return "schedule"
    return "publishing"


def _schedule_node(state: AgentState) -> AgentState:
    """Park approved, future-dated assets in the holding queue; the dispatch cron
    publishes them when due (see POST /scheduled/dispatch). Ends the run here."""
    thread_id = state.get("thread_id", "")
    now = datetime.now(timezone.utc)
    scheduled: list[dict] = []
    for raw in state.get("creative_assets", []):
        asset = PostAsset.model_validate(raw)
        if asset.scheduled_at and asset.scheduled_at > now:
            asset.approval_status = "scheduled"
            enqueue_scheduled(asset.model_dump(mode="json"), thread_id)
        scheduled.append(asset.model_dump(mode="json"))
    return {**state, "status": "scheduled", "creative_assets": scheduled}


def _make_checkpointer():
    """Return a Supabase-backed Postgres checkpointer when credentials are present,
    falling back to in-memory for local dev / CI without a Supabase project."""
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")

    if supabase_url and supabase_key:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            # Supabase exposes a Postgres connection string via the connection pooler.
            # from_conn_string() is a context manager (closes the conn on exit), so for a
            # long-lived server we own a pool and hand PostgresSaver a live one instead.
            db_url = os.environ.get("SUPABASE_DB_URL", "")
            if db_url:
                pool = ConnectionPool(
                    conninfo=db_url,
                    min_size=1,
                    # Supabase's session-mode pooler caps the whole project at 15 clients;
                    # stay well under so migrations/scripts can still connect.
                    max_size=5,
                    open=True,
                    # prepare_threshold=0 keeps us compatible with the pgbouncer pooler
                    kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                )
                saver = PostgresSaver(pool)
                saver.setup()  # idempotent: creates checkpoint tables on first run
                return saver
        except ImportError:
            pass  # langgraph-checkpoint-postgres not installed; fall through

    return MemorySaver()


def build_graph() -> StateGraph:
    checkpointer = _make_checkpointer()
    g = StateGraph(AgentState)

    g.add_node("coordinator", coordinator_node)
    g.add_node("strategy", strategy_node)
    g.add_node("creative", creative_node)
    g.add_node("media_submit", media_submit_node)
    g.add_node("media_await", media_await_node)
    g.add_node("human_approval", _human_approval_node)
    g.add_node("schedule", _schedule_node)
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
    g.add_edge("creative", "media_submit")
    g.add_conditional_edges(
        "media_submit",
        _route_after_media_submit,
        {"media_await": "media_await", "human_approval": "human_approval"},
    )
    g.add_conditional_edges(
        "media_await",
        _route_after_media_await,
        {"media_await": "media_await", "human_approval": "human_approval"},
    )
    g.add_conditional_edges(
        "human_approval",
        _route_after_approval,
        {"publishing": "publishing", "schedule": "schedule", END: END},
    )
    g.add_edge("schedule", END)
    g.add_edge("publishing", "engagement")
    g.add_edge("engagement", "analytics")
    g.add_edge("analytics", END)

    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["media_await", "human_approval"],
    )


graph = build_graph()
