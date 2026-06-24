# n8n Operator Layer + Operator API — Setup

This is the Tier 2 "runs on its own" layer from [production-mvp.md](production-mvp.md). It has
two moving parts:

1. **Operator API** (`src/server/app.py`, FastAPI) — wraps the LangGraph and owns everything
   that needs Python: the graph + Supabase checkpointer, the fal video webhook (download +
   re-host), the Meta comment/DM webhook (signature + `hub.challenge`), and sending the
   Telegram approval card.
2. **n8n** — owns the clock and the human: a 5-minute cron that publishes due scheduled posts,
   an optional daily campaign kickoff, and the Telegram Approve/Reject round-trip.

```
                 ┌────────── n8n ──────────┐
   cron (5m) ───▶│ POST /scheduled/dispatch │───▶┐
   Telegram tap ▶│ POST /runs/{id}/resume   │───▶│
                 └──────────────────────────┘    │
                                                  ▼
   fal.ai  ──webhook──▶  POST /webhooks/fal  ──▶ Operator API ──▶ LangGraph ──▶ Meta Graph API
   Meta    ──webhook──▶  POST /webhooks/meta ──▶ (graph + Supabase + Telegram card)
```

## 1. Run the Operator API

```bash
pip install -r requirements.txt
uvicorn src.server.app:app --host 0.0.0.0 --port 8080
```

On the Hetzner VPS, put it behind Caddy/nginx for HTTPS (Meta and fal require HTTPS webhooks)
and run it under systemd or `pm2`. `PUBLIC_BASE_URL` must be the public HTTPS URL, e.g.
`https://ops.voodoomomo.example`.

Required env (see [.env.example](../.env.example)): `OPERATOR_API_TOKEN`, `PUBLIC_BASE_URL`,
`FAL_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `META_WEBHOOK_VERIFY_TOKEN`,
`META_APP_SECRET`, plus the existing Supabase / Instagram / Anthropic keys.

### Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/campaigns` | `X-Operator-Token` | Start a campaign from a brief; pauses at approval, sends the Telegram card |
| POST | `/runs/{thread_id}/resume` | `X-Operator-Token` | Approve/reject a paused run |
| POST | `/scheduled/dispatch` | `X-Operator-Token` | Publish all due scheduled posts (idempotent) |
| POST | `/webhooks/fal` | `?token=` | fal video-complete callback → re-host + resume |
| GET/POST | `/webhooks/meta` | verify token / HMAC | Live comment & DM ingestion → Engagement |
| GET | `/healthz` | none | Health check |

## 2. Telegram bot

1. Create a bot with [@BotFather](https://t.me/BotFather); copy the token → `TELEGRAM_BOT_TOKEN`.
2. DM the bot once, then get your chat id (e.g. via `@userinfobot`) → `TELEGRAM_CHAT_ID`.
3. The API sends the approval card; n8n's Telegram Trigger handles the button tap.

## 3. Import the n8n workflows

Import [`n8n/01-scheduled-posting.json`](../n8n/01-scheduled-posting.json) and
[`n8n/02-telegram-approval.json`](../n8n/02-telegram-approval.json). Set these n8n env vars
(Settings → Variables, or container env): `OPERATOR_API_URL` (= `PUBLIC_BASE_URL`),
`OPERATOR_API_TOKEN`. Add Telegram API credentials to the approval workflow.

## 4. Register webhooks with the providers

- **fal.ai** — nothing to configure; the API passes `?fal_webhook=` per job, pointing back at
  `PUBLIC_BASE_URL/webhooks/fal` with `thread_id`/`post_id`/`token` baked in.
- **Meta** — in the Meta App dashboard, set the Instagram webhook callback URL to
  `PUBLIC_BASE_URL/webhooks/meta` and the verify token to `META_WEBHOOK_VERIFY_TOKEN`;
  subscribe to `comments` and `messages`.

## How a scheduled, video post flows

1. n8n daily trigger (or you) → `POST /campaigns` with a `reel` brief.
2. Graph runs strategy + creative (Gemini still image), then `media_submit` queues a fal
   image→video job and the run pauses at `media_await`.
3. fal finishes (~10–15 min) → `POST /webhooks/fal` → API re-hosts the MP4 to Supabase, patches
   the asset, resumes → run pauses at `human_approval` and the Telegram card is sent.
4. You tap **Approve** → n8n → `POST /runs/{id}/resume` `{approved:true}`.
5. If `scheduled_at` is in the future, the post is parked in `scheduled_posts`; the 5-minute
   cron's `POST /scheduled/dispatch` publishes it when due. Otherwise it publishes immediately.
6. Publishing is idempotent on `post_id`, so retries never double-post. Trending-audio Reels are
   routed to `manual_publish_queue` instead of auto-publishing.
