# Production MVP Checklist (single cafe)

This is the **shippable-for-one-cafe** path, kept deliberately separate from the
[build/study roadmap](build-schedule.md). The roadmap is for learning (and the CCA-F exam);
this list is only what's needed to run reliably for **Voodoo Momo** without babysitting.

Guiding rule (from the architecture review): **one genuinely agentic component — Engagement.
Everything else stays deterministic, testable, approval-gated, and observable.** Don't add
capability that a single cafe doesn't need yet.

## Tier 1 — reliability backbone  ✅ done in this branch

- [x] **Unified `PostAsset` schema** threading `campaign_id → post_id → image_url → approval_status → published_media_id → metrics` (`src/schemas.py`).
- [x] **Idempotent publish.** Stable `post_id` + per-attempt `publish_attempt_id`; the Publishing node skips a post already published in this state or in a prior run (DB lookup), and a unique index on `post_id` is the DB-level backstop. Prevents double-posting on retries/resumes.
- [x] **Engagement deterministic policy gate** before any reply tool fires (re-checks escalation keywords + validates the drafted reply for banned phrases/length) — the LLM's judgement is never the last line of defence.

## Tier 2 — "runs on its own" (the n8n operator layer)

- [ ] **Scheduled posting** — n8n Schedule trigger calls the graph at planned times (no manual kickoff).
- [ ] **Approve from your phone** — graph pauses at the gate → n8n sends an image+caption card to WhatsApp/Telegram with Approve/Reject → tap resumes the graph.
- [ ] **Live comment/DM ingestion** — Meta webhook → n8n → Engagement (replaces the in-state queue).
- [ ] **Automated token refresh** — cron/n8n runs `scripts/refresh_ig_token.py` before the 60-day expiry.
- [ ] **Scheduling state** — hold approved posts as `scheduled` until their `scheduled_at` (the field exists on `PostAsset`; the holding queue does not yet).

## Tier 3 — close the loop & basic ops

- [ ] **Learning loop** — real embeddings in `brand_memory._embed()` (currently a zero vector); `store_post()` already runs after publish, so once embeddings are real, Strategy can retrieve *high-performing* similar posts.
- [ ] **Analytics writeback** — fetch insights on a schedule and write `metrics` onto the `PostAsset`/`brand_posts` row.
- [ ] **Image decision** — default to **real cafe photos** (often outperform AI for food); enable Gemini billing only when a generated/mascot image is specifically wanted.
- [ ] **Basic observability** — structured publish/error logging good enough to answer "did Friday's post go out, and if not, why?" (full Langfuse tracing/eval-gating is a *before-clients* concern, not single-cafe MVP).

## Explicitly deferred (pre-client / multi-cafe — not MVP)

- Full Langfuse tracing + alerting + eval pass-rate gating in CI
- Approval/audit table (who approved what, and diffs after rejection)
- Dead-letter queues and multi-step retry orchestration
- Multi-tenant isolation (per-cafe state + credentials)
- Secret manager + automated rotation (beyond `.env` / GitHub Secrets)

## Definition of done (single-cafe MVP)

Tier 1 complete **and** Tier 2 complete: the agent posts on schedule, asks for approval on
your phone, replies to comments/DMs live, never double-posts, and refreshes its own token.
Tier 3 makes it *smarter and more observable*, but isn't required to launch.
