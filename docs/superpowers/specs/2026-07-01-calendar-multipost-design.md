# Design: Calendar → multi-post fan-out with per-post weekly approval

**Date:** 2026-07-01
**Status:** Approved (brainstorming)

## Goal

Strategy already builds a 7-day `ContentCalendar`, but `creative_node` drafts a single
post from `state["brief"]` and ignores the calendar. Fan the calendar out into N
`PostAsset`s (one per calendar entry), review the week **per-post** (approve/reject
each), and auto-publish approved posts on their scheduled day. This is the base the
future client approval dashboard sits on.

## Scope

- **Changes:** `creative_node` (fan-out), the approval layer (Telegram callback +
  webhook + resume gating), and post-approval routing.
- **Unchanged:** node graph shape, `media_submit`/`media_await`/`publishing` (already
  iterate `creative_assets`), `schedule_store`/dispatch cron, image + video tools.

## Phase 1 — Creative fan-out

`creative_node` consumes `state["strategy"]` (`ContentCalendar` dict). For each
`ScheduledPost`:

- map → `PostBrief`: `product=topic`, `goal=calendar.goal`, `format`, `variety`; the
  calendar's 1-line `brief` is added to the draft context.
- `draft_caption` → `generate_image` (mascot ref only when the prompt calls for the
  panda — existing `_render_post_image` logic).
- build a `PostAsset` with `scheduled_at = week_start + day_offset` at `POST_HOUR`
  (default `10`, tz `Asia/Kolkata`, both env-overridable).

Emits a **list of N assets**. Per-post confidence gating (<0.7 → that post flagged) and
per-post image-failure flagging reuse today's logic, looped.

**Fallback:** empty/missing/invalid calendar → the current single `state["brief"]`
path, so a degraded strategy run still ships one post.

**Cost:** N posts = N caption LLM calls + N image gens (~$0.025 each on flux/dev;
~$0.13 for a 5-post week). Acceptable; noted so it isn't a surprise.

## Phase 2 — Per-post approval + routing

- **Telegram card** (`send_approval_card`): callback data becomes
  `approve:<thread>:<post_id>` / `reject:<thread>:<post_id>` (was thread-level). One
  card per pending post is already sent by `_notify_if_awaiting_approval`.
- **Webhook** (`/webhooks/telegram`): parse `post_id`, set that asset's
  `approval_status` to `approved`/`rejected` in checkpointed state, acknowledge.
- **Resume gating:** stay paused at `human_approval` until no asset is still
  `pending_approval`; then resume once. Replaces the single global `state["approved"]`.
- **Routing after approval** (`_route_after_approval` + `schedule_node`/
  `publishing_node`, filtered by `approval_status`):
  - `rejected` → skipped, never published.
  - `approved` + future `scheduled_at` → schedule queue → dispatch publishes on its day.
  - `approved` + today/past → publish immediately.
- Operator API `/resume` keeps a bulk-approve convenience path; Telegram is the
  per-post path.

## Error handling

Per-post isolation: one post's caption/image/publish failure flags or fails *that*
post only; siblings proceed. Existing structured errors + recovery hints reused. A
post with no `image_url` never reaches publish (existing guard).

## Testing (TDD, all mocked — no live calls)

Phase 1:
- 3-post calendar → 3 assets; correct `scheduled_at` per `day_offset`; correct
  topic/variety/format mapping.
- Per-post confidence below threshold flags only that post.
- Empty calendar → single fallback asset from `state["brief"]`.

Phase 2:
- Callback `approve:t:p1` parses `post_id=p1`; sets only that asset's status.
- Resume does not fire while any asset is `pending_approval`; fires when all decided.
- Routing: rejected skipped; approved+future → schedule; approved+today → publish.

## Phasing

Phase 1 lands first as a green checkpoint (fan-out works under the interim global
gate). Phase 2 follows on the same branch. Two commits.

## Out of scope

- Client dashboard UI (future; this is its data/approval backbone).
- Caption/image editing in approval (dashboard feature; Telegram stays approve/reject).
- Real embeddings (next task after this).
