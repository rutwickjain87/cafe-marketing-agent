"""Operator API — the FastAPI bridge between the n8n layer (and Meta/fal webhooks)
and the in-process LangGraph.

n8n owns the clock/human-facing work (scheduled dispatch, daily kickoff, Telegram
approve/reject); fal and Meta call their webhooks here directly because they need
Python-side processing (video upload, signature checks). All operator endpoints sit
behind a shared-secret header (X-Operator-Token); webhooks authenticate per their
provider (fal: token query param; Meta: HMAC signature).

Run:  uvicorn src.server.app:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from src import tracing
from src.agents.engagement.engagement import engagement_node
from src.agents.publishing import publishing_node
from src.graph import build_graph
from src.memory.brand_memory import upload_video
from src.memory.schedule_store import fetch_due, mark_dispatched
from src.tools.fal_media import FalError, parse_webhook
from src.tools.notify import answer_callback_query, notify_text, send_approval_card

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process scheduler (replaces n8n's cron). BackgroundScheduler runs jobs on
# its own threads inside this uvicorn process.
# ---------------------------------------------------------------------------
scheduler = BackgroundScheduler(timezone="UTC")


def _job_dispatch() -> None:
    """Publish any due scheduled posts (idempotent). Runs on an interval."""
    try:
        _log.info("scheduled dispatch: %s", dispatch_scheduled())
    except Exception as exc:  # job boundary — one failure must not kill the scheduler
        _log.exception("scheduled dispatch failed")
        notify_text(f"⚠️ Scheduled dispatch error: {exc}")


def _job_daily_kickoff() -> None:
    """Start one campaign/day, paused at approval. Opt-in via env."""
    product = os.environ.get("DAILY_KICKOFF_PRODUCT", "").strip()
    if not product:
        _log.warning("daily kickoff skipped: DAILY_KICKOFF_PRODUCT not set")
        return
    try:
        start_campaign(CampaignRequest(brief={
            "product": product, "goal": "foot_traffic",
            "format": "feed_post", "duration_days": 1,
        }))
    except Exception as exc:
        _log.exception("daily kickoff failed")
        notify_text(f"⚠️ Daily kickoff error: {exc}")


def _start_scheduler() -> None:
    if os.environ.get("SCHEDULER_ENABLED", "true").strip().lower() != "true":
        _log.info("scheduler disabled (SCHEDULER_ENABLED != true)")
        return
    minutes = int(os.environ.get("DISPATCH_INTERVAL_MINUTES", "5"))
    scheduler.add_job(_job_dispatch, "interval", minutes=minutes, id="dispatch", replace_existing=True)
    if os.environ.get("DAILY_KICKOFF_ENABLED", "false").strip().lower() == "true":
        scheduler.add_job(_job_daily_kickoff, "cron", hour=9, minute=0, id="daily_kickoff", replace_existing=True)
    scheduler.start()
    _log.info("APScheduler started — dispatch every %d min", minutes)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _start_scheduler()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)
    tracing.flush()  # ensure buffered Langfuse events are sent on shutdown


app = FastAPI(title="Voodoo Momo Operator API", lifespan=lifespan)
graph = build_graph()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def require_operator_token(x_operator_token: str | None = Header(default=None)) -> None:
    expected = os.environ.get("OPERATOR_API_TOKEN", "")
    if not expected or not x_operator_token or not hmac.compare_digest(x_operator_token, expected):
        raise HTTPException(status_code=401, detail="invalid operator token")


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _pause_point(thread_id: str) -> str | None:
    """The node the graph is paused before, or None if it has finished."""
    snap = graph.get_state(_config(thread_id))
    return snap.next[0] if snap.next else None


def _notify_if_awaiting_approval(thread_id: str) -> None:
    if _pause_point(thread_id) != "human_approval":
        return
    snap = graph.get_state(_config(thread_id))
    for asset in snap.values.get("creative_assets", []):
        send_approval_card(thread_id, asset)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CampaignRequest(BaseModel):
    brief: dict


class CampaignResponse(BaseModel):
    thread_id: str
    campaign_id: str
    status: str
    paused_at: str | None = None


class ResumeRequest(BaseModel):
    approved: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/campaigns", response_model=CampaignResponse, dependencies=[Depends(require_operator_token)])
def start_campaign(req: CampaignRequest) -> CampaignResponse:
    thread_id = f"thread_{uuid.uuid4().hex[:12]}"
    campaign_id = f"camp_{uuid.uuid4().hex[:12]}"
    state = {
        "campaign_id": campaign_id,
        "thread_id": thread_id,
        "brief": req.brief,
        "status": "draft",
    }
    graph.invoke(state, _config(thread_id))
    paused = _pause_point(thread_id)
    if paused == "human_approval":
        _notify_if_awaiting_approval(thread_id)
    snap = graph.get_state(_config(thread_id))
    return CampaignResponse(
        thread_id=thread_id,
        campaign_id=campaign_id,
        status=snap.values.get("status", "draft"),
        paused_at=paused,
    )


def _acknowledge_resume(approved: bool, values: dict) -> None:
    """Tell the operator on Telegram what happened after they approve/reject."""
    if not approved:
        notify_text("🚫 Rejected — post discarded.")
        return
    asset = (values.get("creative_assets") or [{}])[0]
    permalink = asset.get("permalink")
    status = asset.get("approval_status")
    if status == "published" or permalink:
        notify_text(f"✅ Approved & published.\n{permalink or ''}".strip())
    elif status == "manual_queue":
        notify_text("✅ Approved — routed to the manual publish queue (trending audio).")
    else:
        errs = values.get("errors") or []
        notify_text(f"⚠️ Approved but publish failed: {errs[-1] if errs else 'see logs'}")


def _resume_run(thread_id: str, approved: bool) -> dict:
    """Resume a run paused at approval, send a Telegram acknowledgement, report status."""
    if _pause_point(thread_id) != "human_approval":
        return {"thread_id": thread_id, "status": "not_awaiting", "paused_at": _pause_point(thread_id)}
    if approved:
        # Instant feedback — publishing then takes ~10-15s of Meta API calls before
        # the final "published" ack below.
        notify_text("✅ Approved — publishing now…")
    graph.update_state(
        _config(thread_id),
        {"approved": approved, "human_review_required": False},
    )
    graph.invoke(None, _config(thread_id))
    snap = graph.get_state(_config(thread_id))
    _acknowledge_resume(approved, snap.values)
    return {
        "thread_id": thread_id,
        "status": snap.values.get("status", "unknown"),
        "paused_at": _pause_point(thread_id),
    }


def _decide_post(thread_id: str, post_id: str, approved: bool) -> dict:
    """Record a per-post approve/reject, then resume the run only once every post is decided.

    Replaces the single global `approved` flag for the weekly multi-post flow: each tap sets
    one asset's approval_status; the graph stays paused until none remain pending_approval."""
    if _pause_point(thread_id) != "human_approval":
        return {"status": "not_awaiting"}

    assets = list(graph.get_state(_config(thread_id)).values.get("creative_assets", []))
    for asset in assets:
        if asset.get("post_id") == post_id:
            asset["approval_status"] = "approved" if approved else "rejected"
    graph.update_state(_config(thread_id), {"creative_assets": assets})

    pending = [a for a in assets if a.get("approval_status") in ("pending_approval", "draft")]
    if pending:
        return {"decided": post_id, "approved": approved, "remaining": len(pending)}

    any_approved = any(a.get("approval_status") == "approved" for a in assets)
    graph.update_state(_config(thread_id), {"approved": any_approved, "human_review_required": False})
    notify_text("✅ All posts decided — publishing approved ones now…" if any_approved
                else "🚫 All posts rejected — nothing to publish.")
    graph.invoke(None, _config(thread_id))
    out = graph.get_state(_config(thread_id)).values
    return {"resumed": True, "any_approved": any_approved, "status": out.get("status", "unknown")}


@app.post("/runs/{thread_id}/resume", dependencies=[Depends(require_operator_token)])
def resume_run(thread_id: str, req: ResumeRequest) -> dict:
    result = _resume_run(thread_id, req.approved)
    if result["status"] == "not_awaiting":
        raise HTTPException(status_code=409, detail="run is not awaiting approval")
    return result


@app.post("/webhooks/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Handle Approve/Reject inline-button taps from the Telegram approval card.

    Secured by the Telegram secret_token set on setWebhook (we use OPERATOR_API_TOKEN).
    callback_data is 'approve:<thread_id>' / 'reject:<thread_id>'.
    """
    expected = os.environ.get("OPERATOR_API_TOKEN", "")
    if expected and not hmac.compare_digest(x_telegram_bot_api_secret_token or "", expected):
        raise HTTPException(status_code=401, detail="invalid telegram secret")

    update = _parse_json_bytes(await request.body())
    cq = update.get("callback_query")
    if not cq:
        return {"handled": False}

    action, _, rest = (cq.get("data") or "").partition(":")
    thread_id, _, post_id = rest.partition(":")
    approved = action == "approve"
    answer_callback_query(cq.get("id"), "Approving ✅" if approved else "Rejecting 🚫")
    # Per-post cards carry the post_id; legacy thread-level cards fall back to bulk resume.
    result = _decide_post(thread_id, post_id, approved) if post_id else _resume_run(thread_id, approved)
    return {"handled": True, **result}


@app.post("/webhooks/fal")
async def fal_webhook(request: Request, thread_id: str, post_id: str, token: str | None = None) -> dict:
    expected = os.environ.get("OPERATOR_API_TOKEN", "")
    if expected and (not token or not hmac.compare_digest(token, expected)):
        raise HTTPException(status_code=401, detail="invalid webhook token")

    body = _parse_json_bytes(await request.body())
    result = parse_webhook(body)
    if isinstance(result, FalError):
        notify_text(f"⚠️ fal render failed for {post_id}: {result.message}")
        # Resume anyway so the run doesn't hang — media_submit already degraded on submit
        # failure; a post-submit failure here is rare, surface it and leave the run paused.
        raise HTTPException(status_code=200, detail=result.message)

    public_url = _rehost_video(result.video_url)
    _patch_asset_video(thread_id, post_id, public_url, result.thumbnail_url)
    graph.invoke(None, _config(thread_id))
    _notify_if_awaiting_approval(thread_id)
    return {"thread_id": thread_id, "post_id": post_id, "paused_at": _pause_point(thread_id)}


@app.get("/webhooks/meta")
def meta_verify(request: Request) -> PlainTextResponse:
    params = request.query_params
    verify_token = os.environ.get("META_WEBHOOK_VERIFY_TOKEN", "")
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token:
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="verification failed")


@app.post("/webhooks/meta")
async def meta_webhook(request: Request) -> dict:
    raw = await request.body()
    if not _verify_meta_signature(request.headers.get("X-Hub-Signature-256", ""), raw):
        raise HTTPException(status_code=401, detail="invalid signature")
    payload = _parse_json_bytes(raw)
    messages = _normalize_meta_events(payload)
    if not messages:
        return {"handled": 0}

    result = engagement_node({"engagement_queue": messages})
    escalated = result.get("escalated_messages", [])
    if escalated:
        notify_text(f"🙋 {len(escalated)} message(s) escalated for human review.")
    return {"handled": len(messages), "escalated": len(escalated)}


@app.post("/scheduled/dispatch", dependencies=[Depends(require_operator_token)])
def dispatch_scheduled() -> dict:
    due = fetch_due()
    published = 0
    for row in due:
        asset = row.get("asset") or {}
        state = {
            "approved": True,
            "campaign_id": asset.get("campaign_id", ""),
            "creative_assets": [asset],
        }
        out = publishing_node(state)
        for err in out.get("errors", []):
            notify_text(f"⚠️ Scheduled publish error: {err}")
        mark_dispatched(asset.get("post_id", ""))
        published += 1
    return {"due": len(due), "dispatched": published}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_json_bytes(raw: bytes) -> dict:
    import json
    try:
        return json.loads(raw or b"{}")
    except (ValueError, TypeError):
        return {}


def _verify_meta_signature(header: str, raw: bytes) -> bool:
    secret = os.environ.get("META_APP_SECRET", "")
    if not secret:
        _log.warning("META_APP_SECRET not set — rejecting webhook")
        return False
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.split("=", 1)[1], expected)


def _normalize_meta_events(payload: dict) -> list[dict]:
    """Flatten an Instagram webhook payload into IncomingMessage dicts."""
    messages: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") == "comments":
                v = change.get("value", {})
                if v.get("id") and v.get("text"):
                    messages.append({"id": v["id"], "type": "comment", "text": v["text"]})
        for msg in entry.get("messaging", []):
            m = msg.get("message", {})
            sender = msg.get("sender", {}).get("id")
            if m.get("text") and sender:
                messages.append({
                    "id": m.get("mid", sender),
                    "type": "dm",
                    "text": m["text"],
                    "thread_id": sender,
                })
    return messages


def _rehost_video(fal_url: str) -> str:
    """Download the fal clip and re-host it as a public MP4 on Supabase.

    Instagram fetches video_url server-side and fal URLs are short-lived, so we
    rehost on the same public bucket used for images.
    """
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        resp = client.get(fal_url)
        resp.raise_for_status()
    tmp = Path(tempfile.gettempdir()) / f"reel-{uuid.uuid4().hex[:8]}.mp4"
    tmp.write_bytes(resp.content)
    try:
        return upload_video(str(tmp))
    finally:
        tmp.unlink(missing_ok=True)


def _patch_asset_video(thread_id: str, post_id: str, video_url: str, thumbnail_url: str | None) -> None:
    snap = graph.get_state(_config(thread_id))
    assets = list(snap.values.get("creative_assets", []))
    for asset in assets:
        if asset.get("post_id") == post_id:
            asset["video_url"] = video_url
            asset["thumbnail_url"] = thumbnail_url
    graph.update_state(_config(thread_id), {"creative_assets": assets})
