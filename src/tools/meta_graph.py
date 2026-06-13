"""
Meta Graph API tool layer — Phase 2.

Design rules:
- One job per tool; typed inputs and outputs via Pydantic.
- Every failure returns a MetaError with a `recovery` hint the agent can act on.
- Exposed as an MCP server via Composio; register in Claude Code with /mcp.
- Tool distribution (least-privilege):
    publishing tools  → Publishing node only
    comment/DM tools  → Engagement node only
    analytics tools   → Analytics node only

Environment variables required:
    INSTAGRAM_ACCESS_TOKEN  — long-lived Instagram-Login token (60-day; refresh monthly)
    IG_USER_ID              — Instagram-scoped account ID from the token exchange

Auth path: Instagram API with Instagram Login (graph.instagram.com), NOT the
Facebook-Login Graph API. This avoids the New Pages Experience block on user
tokens — no linked Facebook Page is required.
"""
from __future__ import annotations

import os
import time
from enum import Enum
from typing import Union

import httpx
from pydantic import BaseModel

_BASE = "https://graph.instagram.com/v22.0"
_GRAPH_ROOT = "https://graph.instagram.com"  # token-management endpoints are unversioned
_POLL_INTERVAL_S = 5
_POLL_MAX_ATTEMPTS = 24  # 2 minutes at 5s intervals


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------

class MetaErrorCode(str, Enum):
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PAGE_PUBLISH_AUTH_REQUIRED = "PAGE_PUBLISH_AUTH_REQUIRED"
    DM_WINDOW_EXPIRED = "DM_WINDOW_EXPIRED"
    AUDIO_UNAVAILABLE = "AUDIO_UNAVAILABLE"
    CONTAINER_NOT_READY = "CONTAINER_NOT_READY"
    API_ERROR = "API_ERROR"


class MetaError(BaseModel):
    code: MetaErrorCode
    message: str
    recovery: str  # agent-readable hint: "retry_after_60s", "route_to_manual_queue", etc.


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class RefreshedToken(BaseModel):
    access_token: str
    expires_in: int  # seconds until expiry (~60 days)


class MediaContainer(BaseModel):
    container_id: str


class ContainerStatus(BaseModel):
    container_id: str
    status_code: str  # IN_PROGRESS | FINISHED | EXPIRED | ERROR | PUBLISHED


class PublishResult(BaseModel):
    media_id: str
    permalink: str | None = None


class CommentReplyResult(BaseModel):
    reply_id: str


class DmReplyResult(BaseModel):
    message_id: str


class MediaInsights(BaseModel):
    media_id: str
    impressions: int
    reach: int
    likes: int
    comments: int
    saved: int
    shares: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _token() -> str:
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN is not set")
    return token


def _ig_user_id() -> str:
    uid = os.environ.get("IG_USER_ID", "")
    if not uid:
        raise RuntimeError("IG_USER_ID is not set")
    return uid


def _handle_response(resp: httpx.Response) -> Union[dict, MetaError]:
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "60")
        return MetaError(
            code=MetaErrorCode.RATE_LIMITED,
            message="Meta API rate limit hit",
            recovery=f"retry_after_{retry_after}s",
        )
    if resp.status_code == 401:
        return MetaError(
            code=MetaErrorCode.AUTH_REQUIRED,
            message="Access token invalid or expired",
            recovery="refresh_access_token",
        )
    try:
        data = resp.json()
    except Exception:
        return MetaError(
            code=MetaErrorCode.API_ERROR,
            message=f"Non-JSON response: {resp.text[:200]}",
            recovery="inspect_response_and_retry",
        )

    if "error" in data:
        err = data["error"]
        code_int = err.get("code", 0)
        subcode = err.get("error_subcode", 0)
        msg = err.get("message", "Unknown Meta API error")

        # 10 = Application doesn't have permission; 200 = Permissions error (OAuthException)
        if code_int in (10, 200) or subcode == 458:
            return MetaError(
                code=MetaErrorCode.PAGE_PUBLISH_AUTH_REQUIRED,
                message=msg,
                recovery="link_facebook_page_to_instagram_account",
            )
        return MetaError(
            code=MetaErrorCode.API_ERROR,
            message=msg,
            recovery="check_meta_error_code_and_retry",
        )
    return data


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def refresh_long_lived_token(token: str | None = None) -> RefreshedToken | MetaError:
    """Refresh a 60-day Instagram-Login token. Token must be >=24h old.

    Returns a new token with a fresh ~60-day window. Defaults to the current
    INSTAGRAM_ACCESS_TOKEN env var when no token is passed.
    """
    params = {
        "grant_type": "ig_refresh_token",
        "access_token": token or _token(),
    }
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{_GRAPH_ROOT}/refresh_access_token", params=params)

    result = _handle_response(resp)
    if isinstance(result, MetaError):
        return result
    return RefreshedToken(
        access_token=result["access_token"],
        expires_in=result.get("expires_in", 0),
    )


# ---------------------------------------------------------------------------
# Publishing tools (Publishing node only)
# ---------------------------------------------------------------------------

def create_media_container(
    image_url: str,
    caption: str,
    *,
    is_carousel_item: bool = False,
) -> MediaContainer | MetaError:
    """Step 1 of the two-step Instagram container-publish model.

    For Reels, caller must first check for trending audio (AUDIO_UNAVAILABLE risk).
    Returns a container_id to pass to poll_container_status.
    """
    payload: dict = {
        "image_url": image_url,
        "caption": caption,
        "access_token": _token(),
    }
    if is_carousel_item:
        payload["is_carousel_item"] = "true"

    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_BASE}/{_ig_user_id()}/media", data=payload)

    result = _handle_response(resp)
    if isinstance(result, MetaError):
        return result
    return MediaContainer(container_id=result["id"])


def poll_container_status(container_id: str) -> ContainerStatus | MetaError:
    """Poll a single time. Caller loops until status_code == FINISHED or ERROR."""
    params = {
        "fields": "status_code",
        "access_token": _token(),
    }
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{_BASE}/{container_id}", params=params)

    result = _handle_response(resp)
    if isinstance(result, MetaError):
        return result
    return ContainerStatus(
        container_id=container_id,
        status_code=result.get("status_code", "UNKNOWN"),
    )


def wait_for_container(container_id: str) -> ContainerStatus | MetaError:
    """Block until container is FINISHED, ERROR, or max attempts exhausted."""
    for _ in range(_POLL_MAX_ATTEMPTS):
        status = poll_container_status(container_id)
        if isinstance(status, MetaError):
            return status
        if status.status_code in ("FINISHED", "ERROR", "EXPIRED"):
            return status
        time.sleep(_POLL_INTERVAL_S)

    return MetaError(
        code=MetaErrorCode.CONTAINER_NOT_READY,
        message=f"Container {container_id} did not finish within {_POLL_MAX_ATTEMPTS * _POLL_INTERVAL_S}s",
        recovery="retry_publish_later",
    )


def publish_media(container_id: str) -> PublishResult | MetaError:
    """Step 2: publish a FINISHED container. Only call after wait_for_container returns FINISHED."""
    payload = {
        "creation_id": container_id,
        "access_token": _token(),
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_BASE}/{_ig_user_id()}/media_publish", data=payload)

    result = _handle_response(resp)
    if isinstance(result, MetaError):
        return result

    media_id = result["id"]
    permalink = _fetch_permalink(media_id)
    return PublishResult(media_id=media_id, permalink=permalink)


def _fetch_permalink(media_id: str) -> str | None:
    params = {"fields": "permalink", "access_token": _token()}
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{_BASE}/{media_id}", params=params)
    data = resp.json()
    return data.get("permalink")


# ---------------------------------------------------------------------------
# Engagement tools (Engagement node only)
# ---------------------------------------------------------------------------

def reply_to_comment(comment_id: str, message: str) -> CommentReplyResult | MetaError:
    """Post a public reply to a comment on one of our media objects."""
    payload = {
        "message": message,
        "access_token": _token(),
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_BASE}/{comment_id}/replies", data=payload)

    result = _handle_response(resp)
    if isinstance(result, MetaError):
        return result
    return CommentReplyResult(reply_id=result["id"])


def send_dm_reply(thread_id: str, message: str) -> DmReplyResult | MetaError:
    """Reply within an existing user-initiated DM thread.

    Only valid within the 24-hr user-initiated window.
    On DM_WINDOW_EXPIRED: caller must discard, never retry or queue.
    """
    payload = {
        "recipient": {"thread_key": thread_id},
        "message": {"text": message},
        "access_token": _token(),
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_BASE}/me/messages", data=payload)

    result = _handle_response(resp)
    if isinstance(result, MetaError):
        return result

    error_data = result.get("error", {})
    if error_data.get("code") == 551:  # Instagram DM window expired
        return MetaError(
            code=MetaErrorCode.DM_WINDOW_EXPIRED,
            message="24-hour DM window has closed",
            recovery="discard_reply_do_not_retry",
        )
    return DmReplyResult(message_id=result.get("message_id", result.get("mid", "")))


# ---------------------------------------------------------------------------
# Analytics tools (Analytics node only)
# ---------------------------------------------------------------------------

_INSIGHT_METRICS = "impressions,reach,likes,comments,saved,shares"


def get_media_insights(media_id: str) -> MediaInsights | MetaError:
    """Fetch engagement metrics for a published post."""
    params = {
        "metric": _INSIGHT_METRICS,
        "access_token": _token(),
    }
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{_BASE}/{media_id}/insights", params=params)

    result = _handle_response(resp)
    if isinstance(result, MetaError):
        return result

    metrics: dict[str, int] = {}
    for item in result.get("data", []):
        metrics[item["name"]] = item["values"][0]["value"] if item.get("values") else item.get("value", 0)

    return MediaInsights(
        media_id=media_id,
        impressions=metrics.get("impressions", 0),
        reach=metrics.get("reach", 0),
        likes=metrics.get("likes", 0),
        comments=metrics.get("comments", 0),
        saved=metrics.get("saved", 0),
        shares=metrics.get("shares", 0),
    )
