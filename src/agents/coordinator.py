from src.state import AgentState


def coordinator_node(state: AgentState) -> AgentState:
    """Owns the campaign goal; validates inputs and initialises run state."""
    # Phase 3: decompose brief into ordered subtasks; set dependencies
    if not state.get("campaign_id"):
        raise ValueError("campaign_id is required")
    if not state.get("brief"):
        raise ValueError("brief is required")
    return {
        **state,
        "status": "draft",
        "approved": False,
        "human_review_required": False,
        "strategy": None,
        "creative_assets": [],
        "errors": [],
        "manual_publish_queue": [],
    }
