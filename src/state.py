from __future__ import annotations
from typing import TypedDict


class AgentState(TypedDict, total=False):
    # Campaign identity
    campaign_id: str
    status: str  # draft | approved | scheduled | published | done

    # Input
    brief: dict  # product, goal, format, duration_days, variety, notes

    # Node outputs
    strategy: dict | None           # content calendar from strategy_node
    creative_assets: list[dict]     # serialized PostAsset dicts (see src/schemas.py)

    # Approval gate — publishing_node checks this; the hard invariant is never bypassed
    approved: bool
    human_review_required: bool
    confidence_score: float

    # Long-term memory (fetched from Supabase pgvector at run start)
    brand_profile: dict
    past_posts: list[dict]

    # Engagement
    engagement_queue: list[dict]    # [{id, type, text, thread_id?}] — injected by caller
    escalated_messages: list[dict]  # filled by engagement_node when escalation fires

    # Failure handling
    errors: list[str]
    manual_publish_queue: list[dict]  # Reels with trending audio — notify human, don't abort
