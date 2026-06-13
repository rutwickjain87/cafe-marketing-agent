from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, field_validator

from src.memory.brand_memory import fetch_brand_profile
from src.state import AgentState

_VALID_FORMATS = {"feed_post", "carousel", "reel"}
_VALID_GOALS = {"foot_traffic", "awareness", "engagement", "follower_growth", "offer_promotion"}


class CampaignBrief(BaseModel):
    """Typed wrapper around the raw brief dict — validated at graph entry."""
    product: str
    goal: str
    format: Literal["feed_post", "carousel", "reel"] = "feed_post"
    duration_days: int = 7
    variety: str | None = None
    notes: str | None = None

    @field_validator("product")
    @classmethod
    def non_empty_product(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("product cannot be empty")
        return v.strip()

    @field_validator("duration_days")
    @classmethod
    def valid_duration(cls, v: int) -> int:
        if not (1 <= v <= 30):
            raise ValueError("duration_days must be 1–30")
        return v


def coordinator_node(state: AgentState) -> AgentState:
    """Validates inputs and initialises run state.

    Assigns a campaign_id if one isn't already set, then validates the brief
    against CampaignBrief. Any validation failure sets human_review_required
    immediately — the graph will not proceed to strategy.
    """
    campaign_id = state.get("campaign_id") or str(uuid.uuid4())

    if not state.get("brief"):
        return {
            **state,
            "campaign_id": campaign_id,
            "status": "draft",
            "approved": False,
            "human_review_required": True,
            "strategy": None,
            "creative_assets": [],
            "errors": ["brief is required"],
            "manual_publish_queue": [],
            "confidence_score": 0.0,
        }

    try:
        brief = CampaignBrief(**state["brief"])
    except ValueError as exc:
        return {
            **state,
            "campaign_id": campaign_id,
            "status": "draft",
            "approved": False,
            "human_review_required": True,
            "strategy": None,
            "creative_assets": [],
            "errors": [f"Invalid campaign brief: {exc}"],
            "manual_publish_queue": [],
            "confidence_score": 0.0,
        }

    return {
        **state,
        "campaign_id": campaign_id,
        "brief": brief.model_dump(exclude_none=True),
        "status": "draft",
        "approved": False,
        "human_review_required": False,
        "strategy": None,
        "creative_assets": [],
        "errors": [],
        "manual_publish_queue": [],
        "confidence_score": 0.0,
        "brand_profile": fetch_brand_profile(),
        "past_posts": state.get("past_posts", []),
    }
