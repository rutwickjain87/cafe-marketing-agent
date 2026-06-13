# Engagement Agent — DM & Comment Compliance Rules

This file loads ONLY when Claude touches files under `src/agents/engagement/`.
It does not affect any other agent context — this is the path-scoped CLAUDE.md behavior from Phase 0.

## Meta platform constraints

- **24-hour DM window:** only reply to a DM if the user sent the first message AND the conversation is < 24 hours old. Never initiate a DM.
- If a `DM_WINDOW_EXPIRED` error is returned by any tool, discard the reply — do NOT retry or queue it.

## Escalation triggers (route to human, do not auto-reply)

- Complaint or negative sentiment that includes a booking or order reference
- High-value booking inquiry (> 10 people, or catering request)
- Ambiguous intent that could be a legal or compliance issue
- Any message requesting a refund or compensation

## Confidence threshold

- `confidence < 0.7` → set `human_review_required = True`, do not send reply

## Tool access (least privilege)

- **Allowed:** `reply_to_comment`, `send_dm_reply`
- **Never use:** any publishing tool (`create_media_container`, `publish_media`, etc.)
