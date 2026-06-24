"""Supabase-backed holding queue for scheduled posts.

Approved posts whose scheduled_at is in the future are parked here instead of
publishing immediately. An n8n cron calls POST /scheduled/dispatch, which reads
fetch_due() and resumes each due post's graph run to publish it.

Same graceful-degradation contract as brand_memory.py: every function is a safe
no-op when Supabase is not configured, so the graph still runs in local dev / CI.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

_SUPABASE_AVAILABLE = False
try:
    from supabase import create_client
    _SUPABASE_AVAILABLE = True
except ImportError:
    pass

_TABLE = "scheduled_posts"


def _enabled() -> bool:
    return _SUPABASE_AVAILABLE and bool(os.environ.get("SUPABASE_URL"))


def _client():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def enqueue_scheduled(asset: dict, thread_id: str) -> None:
    """Park one approved future-dated asset. Idempotent on post_id (upsert)."""
    if not _enabled():
        _log.info("schedule_store disabled (no Supabase) — not enqueuing %s", asset.get("post_id"))
        return
    try:
        client = _client()
        client.table(_TABLE).upsert({
            "post_id": asset.get("post_id"),
            "campaign_id": asset.get("campaign_id"),
            "thread_id": thread_id,
            "scheduled_at": asset.get("scheduled_at"),
            "status": "scheduled",
            "asset": asset,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="post_id").execute()
    except Exception as exc:  # noqa: BLE001 — never abort the graph on a queue write
        _log.warning("enqueue_scheduled failed for post_id=%s: %s", asset.get("post_id"), exc)


def fetch_due(now: datetime | None = None) -> list[dict]:
    """Return scheduled rows whose time has arrived and that are not yet dispatched."""
    if not _enabled():
        return []
    cutoff = (now or datetime.now(timezone.utc)).isoformat()
    try:
        client = _client()
        result = (
            client.table(_TABLE)
            .select("*")
            .eq("status", "scheduled")
            .lte("scheduled_at", cutoff)
            .execute()
        )
        return result.data or []
    except Exception as exc:  # noqa: BLE001
        _log.warning("fetch_due failed: %s", exc)
        return []


def mark_dispatched(post_id: str) -> None:
    """Flip a row to 'dispatched' so it is published exactly once."""
    if not _enabled() or not post_id:
        return
    try:
        client = _client()
        client.table(_TABLE).update({"status": "dispatched"}).eq("post_id", post_id).execute()
    except Exception as exc:  # noqa: BLE001
        _log.warning("mark_dispatched failed for post_id=%s: %s", post_id, exc)
