from __future__ import annotations
from typing import TypedDict


class AgentState(TypedDict):
    # Campaign identity
    campaign_id: str
    status: str  # draft | approved | scheduled | published | done

    # Input
    brief: dict  # product, goal, format, duration

    # Node outputs
    strategy: dict | None           # Phase 1: content calendar + goals
    creative_assets: list[dict]     # Phase 1: [{post_date, caption, hashtags, cta, confidence, asset_url}]

    # Approval gate — publishing node checks this; never bypass
    approved: bool
    human_review_required: bool
    confidence_score: float         # aggregate; per-asset scores live in creative_assets

    # Long-term memory (fetched from Supabase pgvector at run start)
    brand_profile: dict
    past_posts: list[dict]

    # Failure handling
    errors: list[str]
    manual_publish_queue: list[dict]  # Reels with trending audio; notify human, don't abort run
