from src.state import AgentState


def publishing_node(state: AgentState) -> AgentState:
    """Publishes approved content via Meta Graph API tools."""
    # Hard invariant — never bypass
    if not state.get("approved"):
        raise PermissionError("Cannot publish: approved flag is not set in state")

    # Phase 2: call meta_graph tools per asset
    # AUDIO_UNAVAILABLE → append to manual_publish_queue, continue (don't abort run)
    published: list[dict] = []        # TODO Phase 2
    manual_queue = list(state.get("manual_publish_queue", []))

    return {
        **state,
        "status": "published",
        "creative_assets": published,
        "manual_publish_queue": manual_queue,
    }
