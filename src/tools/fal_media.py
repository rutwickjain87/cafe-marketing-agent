"""fal.ai video generation tool layer — image→video Reels.

Design mirrors src/tools/meta_graph.py:
- One job per function; typed inputs and outputs via Pydantic.
- Every failure returns a FalError with a `recovery` hint the agent can act on.
- httpx directly (no fal SDK), to match the Meta tool layer.

Video generation is async (10–15 min). We submit to fal's queue with a webhook so
completion calls back into the operator API (src/server/app.py) instead of blocking a
graph node. poll_fal_status / get_fal_result exist as a fallback for environments
without a public webhook URL.

Environment variables:
    FAL_KEY           — fal.ai API key (fal.ai/dashboard/keys)
    FAL_VIDEO_MODEL   — queue model id; default below
"""
from __future__ import annotations

import os
from enum import Enum

import httpx
from pydantic import BaseModel

from src.tracing import observe

_QUEUE_BASE = "https://queue.fal.run"
_DEFAULT_MODEL = "fal-ai/kling-video/v2/standard/image-to-video"


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------

class FalErrorCode(str, Enum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    GENERATION_FAILED = "GENERATION_FAILED"
    NOT_READY = "NOT_READY"
    API_ERROR = "API_ERROR"


class FalError(BaseModel):
    code: FalErrorCode
    message: str
    recovery: str  # agent-readable hint: "refresh_fal_key", "retry_after_60s", etc.


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class FalJob(BaseModel):
    request_id: str
    status_url: str | None = None


class FalStatus(BaseModel):
    request_id: str
    status: str  # IN_QUEUE | IN_PROGRESS | COMPLETED


class FalResult(BaseModel):
    request_id: str
    video_url: str
    thumbnail_url: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _key() -> str:
    key = os.environ.get("FAL_KEY", "")
    if not key:
        raise RuntimeError("FAL_KEY is not set")
    return key


def _model() -> str:
    return os.environ.get("FAL_VIDEO_MODEL") or _DEFAULT_MODEL


def _headers() -> dict[str, str]:
    return {"Authorization": f"Key {_key()}", "Content-Type": "application/json"}


def _handle_response(resp: httpx.Response) -> dict | FalError:
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "60")
        return FalError(
            code=FalErrorCode.RATE_LIMITED,
            message="fal.ai rate limit hit",
            recovery=f"retry_after_{retry_after}s",
        )
    if resp.status_code in (401, 403):
        return FalError(
            code=FalErrorCode.AUTH_REQUIRED,
            message="fal.ai key invalid or unauthorized",
            recovery="refresh_fal_key",
        )
    try:
        data = resp.json()
    except ValueError:
        return FalError(
            code=FalErrorCode.API_ERROR,
            message=f"Non-JSON response: {resp.text[:200]}",
            recovery="inspect_response_and_retry",
        )
    if resp.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else None
        return FalError(
            code=FalErrorCode.API_ERROR,
            message=str(detail or data)[:300],
            recovery="check_fal_request_and_retry",
        )
    return data


def _extract_result(model: str, request_id: str, payload: dict) -> FalResult | FalError:
    """Pull the video URL out of a fal result/webhook payload.

    fal image-to-video models return {"video": {"url": ...}}; some wrap it under
    a nested "payload". Tolerate both so a webhook body and a polled result parse
    the same way.
    """
    body = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    video = body.get("video") if isinstance(body, dict) else None
    url = video.get("url") if isinstance(video, dict) else None
    if not url:
        return FalError(
            code=FalErrorCode.GENERATION_FAILED,
            message=f"fal result for {request_id} had no video url: {str(body)[:200]}",
            recovery="resubmit_render_job",
        )
    thumb = body.get("thumbnail_url") or (video.get("thumbnail_url") if isinstance(video, dict) else None)
    return FalResult(request_id=request_id, video_url=url, thumbnail_url=thumb)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@observe(name="fal_submit_image_to_video")
def submit_image_to_video(
    prompt: str,
    image_url: str,
    *,
    aspect_ratio: str = "9:16",
    duration: str = "5",
    webhook_url: str | None = None,
    model: str | None = None,
) -> FalJob | FalError:
    """Queue an image→video render. Returns a FalJob with the request_id to track.

    image_url must be a public URL (fal fetches it server-side). When webhook_url is
    given, fal POSTs the result there on completion — preferred over polling for a
    10–15 min job. Default aspect 9:16 for Reels.
    """
    model_id = model or _model()
    params = {"fal_webhook": webhook_url} if webhook_url else None
    body = {
        "prompt": prompt,
        "image_url": image_url,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_QUEUE_BASE}/{model_id}", headers=_headers(), params=params, json=body)

    result = _handle_response(resp)
    if isinstance(result, FalError):
        return result
    request_id = result.get("request_id")
    if not request_id:
        return FalError(
            code=FalErrorCode.API_ERROR,
            message=f"fal submit returned no request_id: {str(result)[:200]}",
            recovery="inspect_response_and_retry",
        )
    return FalJob(request_id=request_id, status_url=result.get("status_url"))


def poll_fal_status(request_id: str, *, model: str | None = None) -> FalStatus | FalError:
    """Poll a single time. Fallback for when no public webhook URL is available."""
    model_id = model or _model()
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{_QUEUE_BASE}/{model_id}/requests/{request_id}/status",
            headers=_headers(),
        )
    result = _handle_response(resp)
    if isinstance(result, FalError):
        return result
    return FalStatus(request_id=request_id, status=result.get("status", "UNKNOWN"))


def get_fal_result(request_id: str, *, model: str | None = None) -> FalResult | FalError:
    """Fetch the finished video URL. Call only after status is COMPLETED."""
    model_id = model or _model()
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{_QUEUE_BASE}/{model_id}/requests/{request_id}",
            headers=_headers(),
        )
    result = _handle_response(resp)
    if isinstance(result, FalError):
        if result.code == FalErrorCode.API_ERROR and resp.status_code == 202:
            return FalError(
                code=FalErrorCode.NOT_READY,
                message=f"fal request {request_id} not finished",
                recovery="poll_again_later",
            )
        return result
    return _extract_result(model_id, request_id, result)


def parse_webhook(body: dict) -> FalResult | FalError:
    """Parse a fal webhook callback body into a FalResult.

    fal posts {request_id, status, payload, error}. status 'OK' carries the result
    under payload; 'ERROR' carries the failure under error.
    """
    request_id = body.get("request_id", "")
    status = str(body.get("status", "")).upper()
    if status in ("ERROR", "FAILED"):
        return FalError(
            code=FalErrorCode.GENERATION_FAILED,
            message=str(body.get("error") or "fal render failed")[:300],
            recovery="resubmit_render_job",
        )
    return _extract_result(_model(), request_id, body)
