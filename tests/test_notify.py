"""Telegram approval-card keyboard — per-post callback data. No network."""
from src.tools.notify import _approval_keyboard


def test_approval_keyboard_carries_thread_and_post():
    kb = _approval_keyboard("thread_9", "post_42")
    data = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert "approve:thread_9:post_42" in data
    assert "reject:thread_9:post_42" in data
