"""Media render node — submits async fal.ai video jobs for Reel assets.

Split into submit + await so the interrupt is static (interrupt_before) and the
fal submission is never re-run on resume:

  creative → media_submit → (pending?) → media_await ⇄ (still pending) → human_approval

media_submit submits one fal job per video asset and stamps render_request_id, then
returns (state committed). media_await is paused via interrupt_before; the fal webhook
patches video_url onto the asset and resumes. When every video has a url, flow proceeds
to approval. A submit failure degrades the asset to its still image so the post still
ships rather than blocking forever on a callback that never arrives.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlencode

from src.schemas import PostAsset
from src.state import AgentState
from src.tools.fal_media import FalError, submit_image_to_video
from src.tools.notify import notify_text

_log = logging.getLogger(__name__)


def _fal_webhook_url(thread_id: str, post_id: str) -> str | None:
    """fal completion callback URL, carrying the run + asset to resume.

    fal only echoes back the request_id, so we encode thread_id/post_id (and the
    operator token for auth) into the webhook URL itself.
    """
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not base:
        return None
    params = {"thread_id": thread_id, "post_id": post_id}
    token = os.environ.get("OPERATOR_API_TOKEN")
    if token:
        params["token"] = token
    return f"{base}/webhooks/fal?{urlencode(params)}"


def media_submit_node(state: AgentState) -> AgentState:
    """Submit a fal video job for each reel asset that has no clip yet."""
    errors = list(state.get("errors", []))
    thread_id = state.get("thread_id", "")
    updated: list[dict] = []

    for raw in state.get("creative_assets", []):
        asset = PostAsset.model_validate(raw)
        if not asset.needs_render or asset.render_request_id:
            updated.append(asset.model_dump(mode="json"))
            continue

        if not asset.image_url:
            errors.append(f"{asset.post_id}: video asset has no image_url to animate — sending still image")
            asset.media_type = "image"
            updated.append(asset.model_dump(mode="json"))
            continue

        prompt = asset.video_prompt or asset.image_prompt or asset.caption
        webhook_url = _fal_webhook_url(thread_id, asset.post_id)
        job = submit_image_to_video(prompt, asset.image_url, webhook_url=webhook_url)
        if isinstance(job, FalError):
            errors.append(f"{asset.post_id}: fal submit failed {job.code} — {job.recovery}; falling back to still image")
            notify_text(f"⚠️ Video render failed for {asset.post_id} ({job.code}). Posting still image instead.")
            asset.media_type = "image"
            updated.append(asset.model_dump(mode="json"))
            continue

        asset.start_render(job.request_id)
        updated.append(asset.model_dump(mode="json"))

    return {**state, "creative_assets": updated, "errors": errors}


def media_await_node(state: AgentState) -> AgentState:
    """No-op checkpoint. Pausing happens via interrupt_before; the fal webhook resumes."""
    return state


def has_pending_render(state: AgentState) -> bool:
    """True while any reel asset is still waiting on its fal clip."""
    for raw in state.get("creative_assets", []):
        asset = PostAsset.model_validate(raw)
        if asset.needs_render and asset.render_request_id and not asset.video_url:
            return True
    return False
