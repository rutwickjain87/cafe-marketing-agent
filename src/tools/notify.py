"""Telegram operator notifications — approval cards and ops alerts.

Two jobs:
- send_approval_card: posts the post image + caption with inline Approve/Reject
  buttons. n8n's Telegram Trigger catches the button callback and resumes the graph.
- notify_text: plain ops alert (publish failure, escalation, manual-queue item).

httpx directly, structured errors, never aborts the caller — a failed notification
must not crash a publish or a graph run.

Environment variables:
    TELEGRAM_BOT_TOKEN  — from @BotFather
    TELEGRAM_CHAT_ID    — operator chat/user id the bot messages
"""
from __future__ import annotations

import logging
import os

import httpx

_log = logging.getLogger(__name__)
_API = "https://api.telegram.org"


def _config() -> tuple[str, str] | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        _log.info("Telegram not configured (TELEGRAM_BOT_TOKEN/CHAT_ID) — skipping notify")
        return None
    return token, chat_id


def _approval_keyboard(thread_id: str, post_id: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve:{thread_id}:{post_id}"},
            {"text": "❌ Reject", "callback_data": f"reject:{thread_id}:{post_id}"},
        ]]
    }


def send_approval_card(thread_id: str, asset: dict) -> bool:
    """Send one post for phone approval. Returns True if delivered.

    asset is a serialized PostAsset dict; we show its preview media + caption.
    The callback_data carries the thread_id so the resume call can target this run.
    """
    cfg = _config()
    if cfg is None:
        return False
    token, chat_id = cfg

    caption = asset.get("caption", "")
    hashtags = " ".join(asset.get("hashtags", []))
    text = f"🐼 Approve this post?\n\n{caption}\n\n{hashtags}".strip()
    media_url = asset.get("video_url") or asset.get("image_url")
    reply_markup = _approval_keyboard(thread_id, asset.get("post_id", ""))

    try:
        with httpx.Client(timeout=20) as client:
            if media_url and asset.get("media_type") == "video":
                resp = client.post(
                    f"{_API}/bot{token}/sendVideo",
                    json={"chat_id": chat_id, "video": media_url, "caption": text[:1024],
                          "reply_markup": reply_markup},
                )
            elif media_url:
                resp = client.post(
                    f"{_API}/bot{token}/sendPhoto",
                    json={"chat_id": chat_id, "photo": media_url, "caption": text[:1024],
                          "reply_markup": reply_markup},
                )
            else:
                resp = client.post(
                    f"{_API}/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text[:4096], "reply_markup": reply_markup},
                )
        if resp.status_code >= 400:
            _log.warning("Telegram approval card failed (%s): %s", resp.status_code, resp.text[:200])
            return False
        return True
    except httpx.HTTPError as exc:
        _log.warning("Telegram approval card error: %s", exc)
        return False


def answer_callback_query(callback_query_id: str | None, text: str = "") -> bool:
    """Acknowledge an inline-button tap so Telegram stops showing the loading spinner."""
    cfg = _config()
    if cfg is None or not callback_query_id:
        return False
    token, _ = cfg
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                f"{_API}/bot{token}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text},
            )
        return resp.status_code < 400
    except httpx.HTTPError as exc:
        _log.warning("answerCallbackQuery failed: %s", exc)
        return False


def notify_text(message: str) -> bool:
    """Send a plain ops alert. Returns True if delivered."""
    cfg = _config()
    if cfg is None:
        return False
    token, chat_id = cfg
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                f"{_API}/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message[:4096]},
            )
        if resp.status_code >= 400:
            _log.warning("Telegram notify failed (%s): %s", resp.status_code, resp.text[:200])
            return False
        return True
    except httpx.HTTPError as exc:
        _log.warning("Telegram notify error: %s", exc)
        return False
