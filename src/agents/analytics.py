from src.state import AgentState


def analytics_node(state: AgentState) -> AgentState:
    """Pulls post insights and writes results to Supabase pgvector memory."""
    # Phase 5/6: trace results in Langfuse; update past_posts in Supabase
    return {**state, "status": "done"}
