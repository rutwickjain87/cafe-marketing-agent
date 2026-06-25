from __future__ import annotations

import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, field_validator

from src.llm import complete, extract_json
from src.state import AgentState
from src.tracing import observe

_MODEL = "claude-sonnet-4-6"

PostFormat = Literal["feed_post", "carousel", "reel"]
ContentPillar = Literal["product_spotlight", "behind_the_scenes", "community", "offer_event"]

_PILLAR_FREQUENCY = {
    "product_spotlight": 3,
    "behind_the_scenes": 1,
    "community": 1,
    "offer_event": 0,  # as needed
}

_SYSTEM = """\
You are a social media strategist for Voodoo Momo, a specialty momo shop in Wagholi, Pune.
You produce a structured 7-day Instagram content calendar as JSON.

Rules:
- 5 posts per week max (never more than 1 per day)
- Post distribution: 3× product_spotlight, 1× behind_the_scenes, 1× community
- Formats: feed_post (most), carousel for variety showcases
- Avoid Reels unless explicitly in the brief — they require manual audio review
- Each post must reference a specific momo variety or moment from the brief context
- Output ONLY raw JSON — no prose, no markdown fences

Menu (for specificity):
Veg: Steam, Fry, Butter Grill, Tandoori, Peri Peri, Chilly, Kurkure, Choila, Achari
Paneer: Steam, Fry, Butter Grill, Tandoori, Peri Peri, Chilly, Kurkure, Choila, Achari
Chicken: Steam, Fry, Butter Grill, Tandoori, Peri Peri, Chilly, Kurkure, Choila, Achari
Cheese Corn: Steam, Fry, Peri-Peri, Kurkure

Output schema:
{
  "week_start": "YYYY-MM-DD",
  "goal": "<campaign goal>",
  "posts": [
    {
      "day_offset": <0-6>,
      "pillar": "<product_spotlight|behind_the_scenes|community|offer_event>",
      "format": "<feed_post|carousel>",
      "topic": "<specific topic, e.g. 'Cheese Corn Kurkure evening snack'>",
      "brief": "<1-sentence direction for the Creative agent>",
      "variety": "<primary momo variety to feature, or null>"
    }
  ]
}
"""


class ScheduledPost(BaseModel):
    day_offset: int
    pillar: ContentPillar
    format: Literal["feed_post", "carousel"]
    topic: str
    brief: str
    variety: str | None = None

    @field_validator("day_offset")
    @classmethod
    def valid_offset(cls, v: int) -> int:
        if not (0 <= v <= 6):
            raise ValueError("day_offset must be 0–6")
        return v


class ContentCalendar(BaseModel):
    week_start: str
    goal: str
    posts: list[ScheduledPost]

    @field_validator("posts")
    @classmethod
    def check_post_count(cls, v: list[ScheduledPost]) -> list[ScheduledPost]:
        if not (1 <= len(v) <= 7):
            raise ValueError(f"post count {len(v)} out of expected range 1–7")
        return v


@observe(name="build_calendar")
def build_calendar(brief: dict, week_start: date | None = None) -> ContentCalendar:
    """Generate a 7-day content calendar from the campaign brief (strategy LLM pass)."""
    if week_start is None:
        week_start = date.today()

    user_msg = (
        f"Campaign brief:\n{json.dumps(brief, indent=2)}\n\n"
        f"Week starting: {week_start.isoformat()}\n"
        "Produce the 7-day content calendar."
    )

    raw = complete(
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        model=_MODEL,
        max_tokens=2048,
    ).strip()
    data = json.loads(extract_json(raw))
    return ContentCalendar(**data)


def strategy_node(state: AgentState) -> AgentState:
    """Builds a 7-day content calendar from the campaign brief."""
    try:
        calendar = build_calendar(state["brief"])
        strategy = calendar.model_dump()
    except (json.JSONDecodeError, ValueError) as exc:
        strategy = {
            "calendar": [],
            "goals": state["brief"].get("goals", []),
            "error": str(exc),
        }
        return {
            **state,
            "strategy": strategy,
            "errors": state.get("errors", []) + [f"Strategy generation failed: {exc}"],
            "human_review_required": True,
        }

    return {**state, "strategy": strategy}
