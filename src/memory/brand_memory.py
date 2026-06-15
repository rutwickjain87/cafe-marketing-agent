"""Supabase pgvector store for brand memory.

Tables expected in Supabase (run migration in db/schema.sql):
  brand_posts(id uuid, media_id text, caption text, pillar text,
              published_at timestamptz, embedding vector(1536))

Usage:
  profile = fetch_brand_profile()    # static brand config
  past    = fetch_similar_posts(topic, k=5)   # semantic retrieval
  store_post(asset)                   # write back after publish
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

_SUPABASE_AVAILABLE = False

try:
    from supabase import create_client
    _SUPABASE_AVAILABLE = True
except ImportError:
    pass


def _client():
    if not _SUPABASE_AVAILABLE:
        raise RuntimeError("supabase package not installed — run: pip install supabase")
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


# ---------------------------------------------------------------------------
# Brand profile — static document stored in Supabase or loaded from disk
# ---------------------------------------------------------------------------

_BRAND_PROFILE_TABLE = "brand_profile"
_POSTS_TABLE = "brand_posts"
_ARTIFACTS_BUCKET = os.environ.get("SUPABASE_BUCKET", "voodoo-momo-artifacts")


# ---------------------------------------------------------------------------
# Image upload — local file -> public Storage URL for Instagram publishing
# ---------------------------------------------------------------------------

def upload_image(file_path: str, dest_name: str | None = None) -> str:
    """Upload a local image to the public Storage bucket and return its public URL.

    Instagram fetches image_url server-side, so it must be a public HTTPS JPEG.
    Raises on failure — a missing image URL must stop the publish, not pass silently.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {file_path}")

    content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    if content_type not in ("image/jpeg", "image/jpg"):
        raise ValueError(f"Instagram requires JPEG; got {content_type} for {path.name}")

    dest = dest_name or f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{path.name}"
    client = _client()
    client.storage.from_(_ARTIFACTS_BUCKET).upload(
        dest,
        path.read_bytes(),
        {"content-type": content_type, "upsert": "true"},
    )
    return client.storage.from_(_ARTIFACTS_BUCKET).get_public_url(dest)

_FALLBACK_PROFILE: dict = {
    "name": "Voodoo Momo",
    "instagram": "@voodoomomo",
    "tagline": "Taste the Himalayan Magic!",
    "tone": "warm, fun, street-style",
    "core_hashtags": ["#VoodooMomo", "#PuneSpecialtyMomo", "#WagholiEats"],
    "banned_phrases": [
        "best momos", "you deserve", "indulge yourself",
        "game-changer", "life-changing", "mind-blowing",
    ],
}


def fetch_brand_profile() -> dict:
    """Return the brand profile dict.

    Falls back to the hardcoded baseline when Supabase is not configured,
    so the graph runs end-to-end in local dev without a DB.
    """
    if not _SUPABASE_AVAILABLE or not os.environ.get("SUPABASE_URL"):
        return _FALLBACK_PROFILE

    try:
        client = _client()
        result = client.table(_BRAND_PROFILE_TABLE).select("*").limit(1).execute()
        if result.data:
            return result.data[0]
    except Exception:
        pass

    return _FALLBACK_PROFILE


# ---------------------------------------------------------------------------
# Past posts — semantic retrieval via pgvector
# ---------------------------------------------------------------------------

def fetch_similar_posts(topic: str, k: int = 5) -> list[dict]:
    """Return up to k past posts semantically similar to topic.

    Requires the `match_brand_posts` RPC function (see db/schema.sql).
    Returns an empty list when Supabase is not available.
    """
    if not _SUPABASE_AVAILABLE or not os.environ.get("SUPABASE_URL"):
        return []

    try:
        embedding = _embed(topic)
        client = _client()
        result = client.rpc(
            "match_brand_posts",
            {"query_embedding": embedding, "match_count": k},
        ).execute()
        return result.data or []
    except Exception:
        return []


def find_published_media(post_id: str) -> str | None:
    """Idempotency lookup: media_id if this post_id was already published, else None.

    Lets the Publishing node skip a post that a previous run already published,
    even after a graph resume. Returns None on any failure (fail-open to a fresh
    publish is acceptable; the DB unique index on post_id is the backstop).
    """
    if not post_id or not _SUPABASE_AVAILABLE or not os.environ.get("SUPABASE_URL"):
        return None
    try:
        client = _client()
        result = (
            client.table(_POSTS_TABLE)
            .select("media_id")
            .eq("post_id", post_id)
            .limit(1)
            .execute()
        )
        row = result.data[0] if result.data else None
        if isinstance(row, dict) and row.get("media_id"):
            return str(row["media_id"])
    except Exception as exc:
        # Fail-open: a fresh publish is acceptable (the DB unique index is the
        # backstop), but log it — a silent miss here weakens idempotency.
        _log.warning("idempotency lookup failed for post_id=%s: %s", post_id, exc)
        return None
    return None


def store_post(asset: dict) -> None:
    """Persist a published asset to brand memory (learning loop + idempotency record).

    Tolerant of both the PostAsset shape (`published_media_id`) and the legacy
    `media_id` key. Never aborts the graph on failure.
    """
    if not _SUPABASE_AVAILABLE or not os.environ.get("SUPABASE_URL"):
        return

    media_id = asset.get("published_media_id") or asset.get("media_id") or ""
    if not media_id:
        return  # nothing was published — nothing to record

    try:
        caption = asset.get("caption", "")
        client = _client()
        client.table(_POSTS_TABLE).insert({
            "post_id": asset.get("post_id"),
            "media_id": media_id,
            "caption": caption,
            "pillar": asset.get("pillar", ""),
            "format": asset.get("format"),
            "permalink": asset.get("permalink"),
            "metrics": asset.get("metrics"),
            "published_at": datetime.now(timezone.utc).isoformat(),
            "embedding": _embed(caption),
            "raw": json.dumps(asset, default=str),
        }).execute()
    except Exception as exc:
        # Never abort the graph on a memory write — but do surface it: this row
        # is also the idempotency record, so a silent failure matters.
        _log.warning("store_post failed for media_id=%s: %s", media_id, exc)


# ---------------------------------------------------------------------------
# Embedding helper — uses OpenAI-compatible endpoint via Supabase AI or
# a local sentence-transformers model when SUPABASE_URL is absent.
# Phase 4: wire to actual embedding model.
# ---------------------------------------------------------------------------

def _embed(text: str) -> list[float]:
    """Return a 1536-dim embedding vector for text.

    Placeholder returns a zero vector. Replace with a real embedding call
    (e.g. anthropic.Embeddings or OpenAI embeddings) before Phase 4 goes live.
    """
    return [0.0] * 1536
