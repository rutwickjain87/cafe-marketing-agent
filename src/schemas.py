"""Cross-cutting domain schemas threaded through the whole pipeline.

`PostAsset` is the single object that follows one post from idea → creative →
approval → published media → metrics. Because every stage keys off the same
stable `post_id`, idempotency, audit, and the learning loop all line up on one
record instead of loose dicts.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

PostFormat = Literal["feed_post", "carousel", "reel"]

MediaType = Literal["image", "video"]

ApprovalStatus = Literal[
    "draft",            # created, not yet ready for review
    "pending_approval", # waiting at the human gate
    "approved",         # human said yes
    "rejected",         # human said no
    "scheduled",        # approved, waiting for its publish time
    "publishing",       # publish in progress (an attempt is live)
    "published",        # live on Instagram
    "manual_queue",     # routed for manual handling (e.g. trending-audio Reel)
    "failed",           # a publish attempt errored
]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostAsset(BaseModel):
    """One post, threaded campaign → idea → asset → published media → metrics."""

    # --- identity (stable for the life of the post; the idempotency key) ---
    post_id: str = Field(default_factory=lambda: _new_id("post"))
    campaign_id: str = ""

    # --- planning (from Strategy) ---
    pillar: str = ""
    format: PostFormat = "feed_post"
    topic: str | None = None
    variety: str | None = None
    scheduled_at: datetime | None = None

    # --- creative (from Creative) ---
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    cta: str = ""
    media_type: MediaType = "image"
    image_url: str | None = None
    image_prompt: str | None = None
    # video (reels) — rendered async by fal.ai from image_url; see src/tools/fal_media.py
    video_url: str | None = None
    video_prompt: str | None = None
    thumbnail_url: str | None = None
    render_request_id: str | None = None  # fal queue job id; idempotency key for re-render
    confidence: float = 0.0

    # --- lifecycle ---
    approval_status: ApprovalStatus = "draft"

    # --- publish (idempotency + result) ---
    publish_attempt_id: str | None = None   # new id per attempt; lets retries be traced
    published_media_id: str | None = None   # set once, only when live
    permalink: str | None = None

    # --- learning ---
    metrics: dict | None = None

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def caption_with_hashtags(self) -> str:
        return f"{self.caption}\n\n{' '.join(self.hashtags)}".strip()

    def start_render(self, request_id: str) -> None:
        """Record a submitted fal.ai render job. Stamps the job id for idempotent re-render."""
        self.render_request_id = request_id
        self.updated_at = _now()

    def mark_rendered(self, video_url: str, thumbnail_url: str | None = None) -> None:
        self.video_url = video_url
        self.thumbnail_url = thumbnail_url
        self.updated_at = _now()

    @property
    def needs_render(self) -> bool:
        """A video asset whose clip has not been produced yet."""
        return self.media_type == "video" and not self.video_url

    @property
    def publish_url(self) -> str | None:
        """The asset the publisher hands to Meta — video for reels, image otherwise."""
        return self.video_url if self.media_type == "video" else self.image_url

    def start_publish_attempt(self) -> str:
        """Begin a new publish attempt; returns its id. Use before calling the API."""
        self.publish_attempt_id = _new_id("pub")
        self.approval_status = "publishing"
        self.updated_at = _now()
        return self.publish_attempt_id

    def mark_published(self, media_id: str, permalink: str | None) -> None:
        self.published_media_id = media_id
        self.permalink = permalink
        self.approval_status = "published"
        self.updated_at = _now()

    @property
    def is_published(self) -> bool:
        return bool(self.published_media_id)
