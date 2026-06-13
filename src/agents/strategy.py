from src.state import AgentState


def strategy_node(state: AgentState) -> AgentState:
    """Builds a 7-day content calendar from the campaign brief."""
    # Phase 1/3: call Claude with explicit criteria + few-shot examples
    # Output: strategy dict with daily post schedule, formats, and goals
    strategy: dict = {
        "calendar": [],  # TODO Phase 1 — [{date, format, topic, goal}]
        "goals": state["brief"].get("goals", []),
    }
    return {**state, "strategy": strategy}
