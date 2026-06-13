from __future__ import annotations

from src.state import AgentState
from src.tools.meta_graph import (
    MetaError,
    MetaErrorCode,
    create_media_container,
    wait_for_container,
    publish_media,
)


def _publish_asset(asset: dict) -> tuple[dict, str | None]:
    """Attempt to publish one creative asset.

    Returns (updated_asset, error_message | None).
    Assets without an image_url are skipped with a flagged error.
    """
    image_url = asset.get("image_url", "")
    caption = asset.get("caption", "")
    full_caption = f"{caption}\n\n{' '.join(asset.get('hashtags', []))}"

    if not image_url:
        asset["status"] = "skipped_no_image_url"
        return asset, "asset has no image_url — skipped"

    container = create_media_container(image_url, full_caption)
    if isinstance(container, MetaError):
        if container.code == MetaErrorCode.AUDIO_UNAVAILABLE:
            asset["status"] = "manual_queue"
            return asset, None  # caller routes to manual_publish_queue
        asset["status"] = "error"
        return asset, f"create_media_container failed: {container.code} — {container.recovery}"

    status = wait_for_container(container.container_id)
    if isinstance(status, MetaError):
        asset["status"] = "error"
        return asset, f"poll failed: {status.code} — {status.recovery}"

    if status.status_code != "FINISHED":
        asset["status"] = "error"
        return asset, f"container ended in status {status.status_code}"

    result = publish_media(container.container_id)
    if isinstance(result, MetaError):
        asset["status"] = "error"
        return asset, f"publish_media failed: {result.code} — {result.recovery}"

    asset["media_id"] = result.media_id
    asset["permalink"] = result.permalink
    asset["status"] = "published"
    return asset, None


def publishing_node(state: AgentState) -> AgentState:
    """Publishes approved creative assets via the Meta Graph API.

    Hard invariant: approved must be True — checked first, no bypass.
    AUDIO_UNAVAILABLE assets are silently routed to manual_publish_queue
    so the run does not abort.
    """
    if not state.get("approved"):
        raise PermissionError("Cannot publish: approved flag is not set in state")

    published: list[dict] = []
    manual_queue = list(state.get("manual_publish_queue", []))
    errors = list(state.get("errors", []))

    for asset in state.get("creative_assets", []):
        updated, err = _publish_asset(dict(asset))
        if err:
            errors.append(err)
        if updated.get("status") == "manual_queue":
            manual_queue.append(updated)
        else:
            published.append(updated)

    return {
        **state,
        "status": "published",
        "creative_assets": published,
        "manual_publish_queue": manual_queue,
        "errors": errors,
    }
