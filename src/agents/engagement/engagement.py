from src.state import AgentState

# Phrases that trigger immediate escalation to a human
ESCALATION_KEYWORDS = ("complaint", "refund", "booking", "catering", "legal", "compensation")


def _should_escalate(message: str) -> bool:
    return any(kw in message.lower() for kw in ESCALATION_KEYWORDS)


def engagement_node(state: AgentState) -> AgentState:
    """Triages incoming comments and DMs.

    This is the only true agentic loop in the system — it handles
    unpredictable, user-initiated interactions. All other nodes are
    deterministic pipelines.

    Phase 3/4: classify → reply (within 24-hr window) or escalate.
    """
    # TODO Phase 3: implement agentic classify → reply loop
    # - Fetch unread comments and DMs via meta_graph tools
    # - Classify each with confidence score
    # - Escalate if _should_escalate or confidence < 0.7
    # - Reply if user-initiated and within 24-hr window
    return {**state}
