from src.state import AgentState

CONFIDENCE_THRESHOLD = 0.7


def creative_node(state: AgentState) -> AgentState:
    """Drafts captions, hashtags, and asset lists for each scheduled post."""
    # Phase 1: structured output with validation + retry loop
    # Phase 5: few-shot library; JSON schema for the full 30-day calendar object
    assets: list[dict] = []  # TODO Phase 1 — [{post_date, caption, hashtags, cta, confidence}]
    confidence = 0.0          # aggregate confidence across all drafts

    return {
        **state,
        "creative_assets": assets,
        "confidence_score": confidence,
        "human_review_required": confidence < CONFIDENCE_THRESHOLD,
    }
