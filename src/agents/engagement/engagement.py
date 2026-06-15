"""Engagement node — the only true agentic loop in the system.

Classifies incoming comments and DMs with Claude Haiku, then:
- Escalates to human if confidence < 0.7 or ESCALATION_KEYWORDS are hit
- Replies to comments with a short on-brand response
- Replies to DMs only within the 24-hr user-initiated window
- Discards DM replies silently on DM_WINDOW_EXPIRED (never retries)
"""
from __future__ import annotations

import json
import os
from typing import Literal

import anthropic
from pydantic import BaseModel

from src.state import AgentState
from src.tools.meta_graph import (
    MetaError,
    MetaErrorCode,
    reply_to_comment,
    send_dm_reply,
)

_MODEL = "claude-haiku-4-5-20251001"
CONFIDENCE_THRESHOLD = 0.7
ESCALATION_KEYWORDS = (
    "complaint", "refund", "booking", "catering", "legal", "compensation",
    "sick", "food poisoning", "rotten", "stale",
)

# Deterministic guardrails applied to the LLM's drafted reply *before* any tool
# fires — the model's own judgement is never the last line of defence.
_BANNED_REPLY_PHRASES = (
    "best momos", "you deserve", "indulge yourself",
    "game-changer", "life-changing", "mind-blowing",
)
_MAX_REPLY_LEN = 500  # Instagram comment/DM safety cap

MessageType = Literal["comment", "dm"]


class IncomingMessage(BaseModel):
    id: str
    type: MessageType
    text: str
    thread_id: str | None = None  # DMs only


class ClassificationResult(BaseModel):
    intent: Literal["question", "compliment", "complaint", "booking", "spam", "other"]
    suggested_reply: str
    confidence: float
    escalate: bool


_CLASSIFY_SYSTEM = """\
You are a social media assistant for Voodoo Momo, a momo shop in Wagholi, Pune.
Classify an incoming Instagram message and draft a short on-brand reply.

Brand voice: warm, street-style, local, honest. "We" POV. Max 1 exclamation mark.
Never: all-caps, "best momos in Pune", "you deserve", "indulge yourself".

Output JSON only:
{
  "intent": "<question|compliment|complaint|booking|spam|other>",
  "suggested_reply": "<reply text, under 120 chars>",
  "confidence": <0.0–1.0>,
  "escalate": <true if complaint / booking > 10 people / ambiguous legal context>
}
"""


def _classify(message: IncomingMessage) -> ClassificationResult:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=256,
        system=_CLASSIFY_SYSTEM,
        messages=[{"role": "user", "content": f"Message: {message.text}"}],
    )
    data = json.loads(resp.content[0].text.strip())
    return ClassificationResult(**data)


def _should_escalate(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in ESCALATION_KEYWORDS)


def _reply_passes_policy(message: IncomingMessage, reply: str) -> tuple[bool, str]:
    """Deterministic gate run right before any reply tool fires.

    Belt-and-suspenders: even after the LLM clears classification and confidence,
    we re-check the incoming text and the drafted reply against hard rules. A
    failure escalates to a human rather than sending.
    """
    if _should_escalate(message.text):
        return False, "keyword_match"
    text = reply.strip()
    if not text:
        return False, "empty_reply"
    if len(text) > _MAX_REPLY_LEN:
        return False, "reply_too_long"
    lower = text.lower()
    if any(phrase in lower for phrase in _BANNED_REPLY_PHRASES):
        return False, "banned_phrase_in_reply"
    return True, ""


def _process_message(
    message: IncomingMessage,
    errors: list[str],
    escalated: list[dict],
) -> None:
    """Classify one message and act: reply, escalate, or discard."""
    if _should_escalate(message.text):
        escalated.append({"id": message.id, "type": message.type, "reason": "keyword_match"})
        return

    try:
        result = _classify(message)
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(f"Classification failed for {message.id}: {exc}")
        escalated.append({"id": message.id, "type": message.type, "reason": "classification_error"})
        return

    if result.escalate or result.confidence < CONFIDENCE_THRESHOLD:
        escalated.append({
            "id": message.id,
            "type": message.type,
            "reason": "escalate_flag" if result.escalate else "low_confidence",
            "confidence": result.confidence,
        })
        return

    # Final deterministic gate before any tool fires.
    allowed, reason = _reply_passes_policy(message, result.suggested_reply)
    if not allowed:
        escalated.append({"id": message.id, "type": message.type, "reason": f"policy:{reason}"})
        return

    if message.type == "comment":
        reply_result = reply_to_comment(message.id, result.suggested_reply)
        if isinstance(reply_result, MetaError):
            errors.append(f"Comment reply failed {message.id}: {reply_result.code}")

    elif message.type == "dm":
        if not message.thread_id:
            errors.append(f"DM {message.id} has no thread_id — skipped")
            return
        reply_result = send_dm_reply(message.thread_id, result.suggested_reply)
        if isinstance(reply_result, MetaError):
            if reply_result.code == MetaErrorCode.DM_WINDOW_EXPIRED:
                pass  # discard silently — per compliance rules
            else:
                errors.append(f"DM reply failed {message.id}: {reply_result.code}")


def engagement_node(state: AgentState) -> AgentState:
    """Triages incoming comments and DMs from state["engagement_queue"]."""
    queue: list[dict] = state.get("engagement_queue", [])  # type: ignore[typeddict-item]
    errors: list[str] = list(state.get("errors", []))
    escalated: list[dict] = []

    for raw in queue:
        try:
            message = IncomingMessage(**raw)
        except ValueError as exc:
            errors.append(f"Invalid message in engagement_queue: {exc}")
            continue
        _process_message(message, errors, escalated)

    updates: dict = {"errors": errors}
    if escalated:
        updates["human_review_required"] = True
        updates["escalated_messages"] = escalated  # type: ignore[typeddict-unknown-key]

    return {**state, **updates}
