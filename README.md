# Cafe Marketing Agent

AI-powered Instagram marketing automation for an independent cafe (**Voodoo Momo**, Wagholi, Pune), built with LangGraph + Claude. Drafts on-brand captions, stages each post behind a human-approval gate, publishes to Instagram, and triages comments/DMs. Image generation (fal.ai) and brand memory are wired as supporting tools — see the [production checklist](docs/production-mvp.md) for what's pipeline-wired vs tool-only today.

Doubles as study for the **Claude Certified Architect – Foundations (CCA-F)** exam — each build phase maps to a specific exam domain. See [docs/roadmap.md](docs/roadmap.md) for the domain mapping and [docs/build-schedule.md](docs/build-schedule.md) for the phase-by-phase plan.

## Architecture

A deterministic LangGraph pipeline with one human gate and one true agentic loop (Engagement):

```
Coordinator → Strategy → Creative → [human approval] → Publishing → Engagement → Analytics
              calendar    caption +                     Instagram     comments     insights
              goals       image (fal.ai)                Graph API     + DMs
```

- **`publish` is unreachable unless `approved == True`** — a hard invariant enforced by the graph's `interrupt_before` gate.
- Every agent output carries a `confidence_score`; below `0.7` sets `human_review_required`.
- Least-privilege tools: publishing tools live only in the Publishing node, comment/DM tools only in Engagement.

## Project layout

```
src/
  graph.py            LangGraph wiring + approval gate + checkpointer
  state.py            AgentState (TypedDict)
  tracing.py          Langfuse @observe shim (no-op until configured)
  agents/             coordinator, strategy, creative, publishing, analytics
    engagement/       the one true agentic loop (path-scoped DM rules in CLAUDE.md)
  tools/              meta_graph.py (Instagram Graph API), image_gen.py (pluggable image providers), image_providers/ (fal.ai FLUX)
  memory/             brand_memory.py (Supabase pgvector + Storage upload)
db/schema.sql         Supabase tables, match_brand_posts RPC, RLS
docs/                 setup guides, brand voice, roadmap, build schedule
assets/brand/         brand poster, mascot, menu, display pic
evals/                brand-compliance eval harness
scripts/              refresh_ig_token.py (60-day token refresh)
```

## Quick start

```bash
cp .env.example .env        # fill in values — see the setup guides below
pip install -r requirements-dev.txt
pytest tests/ -q            # 57 unit tests, no API calls
```

Setup guides:
- **Instagram publishing:** [docs/instagram-api-setup.md](docs/instagram-api-setup.md) — uses the Instagram-Login API (`graph.instagram.com`), which needs **no Facebook Page** and sidesteps the New Pages Experience block.
- **Supabase (memory + checkpointer + image storage):** [docs/supabase-setup.md](docs/supabase-setup.md)

## Stack

- **Orchestration:** LangGraph (Postgres checkpointer via Supabase, else in-memory)
- **Brain:** Claude — Haiku for caption drafts, Sonnet for strategy/review
- **Images:** fal.ai behind a pluggable provider seam (`IMAGE_PROVIDER`, default `fal`) — FLUX dev for product shots, FLUX Kontext for mascot reference-consistency. Shares `FAL_KEY` with video.
- **Publishing:** Instagram Graph API with Instagram Login
- **Memory & storage:** Supabase (pgvector brand memory + public Storage bucket for post images)
- **Observability:** Langfuse (Phase 5+)
- **CI/CD:** GitHub Actions

## Adapting to a new restaurant

This repo is configured end-to-end for Voodoo Momo. Pointing it at a different
restaurant needs **no architecture changes** — only content and credentials:

1. **Credentials & config** — `cp .env.example .env` and fill in your own:
   `FAL_KEY`, `INSTAGRAM_ACCESS_TOKEN` + `IG_USER_ID`, `SUPABASE_*`,
   `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, `OPENROUTER_API_KEY`. Set
   `SUPABASE_BUCKET` to your own **public** bucket.
2. **Brand voice** — [docs/brand-voice.md](docs/brand-voice.md) is the single brand
   guide (identity, tone, hashtags, image rules, few-shot captions). Rewrite it for the
   new brand; `CLAUDE.md` pulls it in via `@docs/brand-voice.md`.
3. **Hardcoded brand in prompts** — the menu, location, tone, and mascot are embedded
   in the system prompts. Update:
   - `src/agents/strategy.py` → `_SYSTEM` (menu, location, content pillars)
   - `src/agents/creative.py` → `_SYSTEM_PROMPT`, `_IMAGE_STYLE_ANCHOR`, `_MASCOT_REF`,
     few-shot examples, and `BANNED_PHRASES` / `BANNED_HASHTAGS` / `CORE_HASHTAGS`
   - `src/agents/engagement/engagement.py` → reply tone / policy keywords
4. **Brand assets** — replace `assets/brand/*` (mascot, menu, poster) with the new
   restaurant's. The mascot reference drives image character-consistency.
5. **Project memory** — `CLAUDE.md` describes Voodoo Momo's conventions + brand profile;
   update the brand-specific lines.
6. **Infra** — a new Supabase project (run `db/schema.sql`), a new Instagram-Login app +
   token ([docs/instagram-api-setup.md](docs/instagram-api-setup.md)), and a new Telegram bot.

`pytest tests/ -q` validates schema/validators and wiring, not brand copy — it stays
green as you adapt.

## Status

Phases 0–6 implemented and wired. Live posts published to [@voodoomomo](https://www.instagram.com/voodoomomo/) — the full draft → approval → publish path is proven end-to-end, with images generated on fal.ai. See [docs/roadmap.md](docs/roadmap.md) for remaining hardening work.
