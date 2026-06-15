from __future__ import annotations

from src.schemas import PostAsset
from src.state import AgentState
from src.memory.brand_memory import find_published_media, store_post
from src.tools.meta_graph import (
    MetaError,
    MetaErrorCode,
    create_media_container,
    wait_for_container,
    publish_media,
)


def _coerce_asset(raw: dict, campaign_id: str) -> PostAsset:
    """Build a PostAsset from a state dict, tolerating the legacy asset shape."""
    data = dict(raw)
    data.setdefault("campaign_id", campaign_id or "unknown")
    if "media_id" in data and not data.get("published_media_id"):
        data["published_media_id"] = data.pop("media_id")
    return PostAsset.model_validate(data)


def _publish_asset(asset: PostAsset) -> tuple[PostAsset, str | None]:
    """Publish one asset, idempotently. Returns (updated_asset, error | None)."""
    # Idempotency guard 1 — already published earlier in this same state.
    if asset.is_published:
        asset.approval_status = "published"
        return asset, None

    # Idempotency guard 2 — published by a prior run (survives a graph resume).
    prior_media_id = find_published_media(asset.post_id)
    if prior_media_id:
        asset.mark_published(prior_media_id, asset.permalink)
        return asset, None

    if not asset.image_url:
        asset.approval_status = "failed"
        return asset, f"post {asset.post_id} has no image_url — skipped"

    asset.start_publish_attempt()  # stamps a publish_attempt_id for tracing
    container = create_media_container(asset.image_url, asset.caption_with_hashtags())
    if isinstance(container, MetaError):
        if container.code == MetaErrorCode.AUDIO_UNAVAILABLE:
            asset.approval_status = "manual_queue"
            return asset, None  # caller routes to manual_publish_queue
        asset.approval_status = "failed"
        return asset, f"create_media_container failed: {container.code} — {container.recovery}"

    status = wait_for_container(container.container_id)
    if isinstance(status, MetaError):
        asset.approval_status = "failed"
        return asset, f"poll failed: {status.code} — {status.recovery}"
    if status.status_code != "FINISHED":
        asset.approval_status = "failed"
        return asset, f"container ended in status {status.status_code}"

    result = publish_media(container.container_id)
    if isinstance(result, MetaError):
        asset.approval_status = "failed"
        return asset, f"publish_media failed: {result.code} — {result.recovery}"

    asset.mark_published(result.media_id, result.permalink)
    store_post(asset.model_dump(mode="json"))  # learning-loop + idempotency record
    return asset, None


def publishing_node(state: AgentState) -> AgentState:
    """Publishes approved assets via the Meta Graph API — idempotently.

    Hard invariant: approved must be True (checked first, no bypass).
    Each asset carries a stable post_id; a post already published (in this state
    or in a prior run) is skipped rather than posted twice. AUDIO_UNAVAILABLE
    assets are routed to manual_publish_queue so the run does not abort.
    """
    if not state.get("approved"):
        raise PermissionError("Cannot publish: approved flag is not set in state")

    campaign_id = state.get("campaign_id", "")
    published: list[dict] = []
    manual_queue = list(state.get("manual_publish_queue", []))
    errors = list(state.get("errors", []))

    for raw in state.get("creative_assets", []):
        asset, err = _publish_asset(_coerce_asset(dict(raw), campaign_id))
        if err:
            errors.append(err)
        dumped = asset.model_dump(mode="json")
        if asset.approval_status == "manual_queue":
            manual_queue.append(dumped)
        else:
            published.append(dumped)

    return {
        **state,
        "status": "published",
        "creative_assets": published,
        "manual_publish_queue": manual_queue,
        "errors": errors,
    }
