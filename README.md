# Cafe Marketing Agent

AI-powered Instagram marketing automation for an independent cafe (**Voodoo Momo**, Wagholi, Pune), built with LangGraph + Claude. Drafts on-brand captions, stages each post behind a human-approval gate, publishes to Instagram, and triages comments/DMs. Image generation (Gemini) and brand memory are wired as supporting tools — see the [production checklist](docs/production-mvp.md) for what's pipeline-wired vs tool-only today.

Doubles as study for the **Claude Certified Architect – Foundations (CCA-F)** exam — each build phase maps to a specific exam domain. See [docs/roadmap.md](docs/roadmap.md) for the domain mapping and [docs/build-schedule.md](docs/build-schedule.md) for the phase-by-phase plan.

## Architecture

A deterministic LangGraph pipeline with one human gate and one true agentic loop (Engagement):

```
Coordinator → Strategy → Creative → [human approval] → Publishing → Engagement → Analytics
              calendar    caption +                     Instagram     comments     insights
              goals       image (Gemini)                Graph API     + DMs
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
  tools/              meta_graph.py (Instagram Graph API), image_gen.py (Gemini)
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
pytest -q                   # 15 unit tests, no API calls
```

Setup guides:
- **Instagram publishing:** [docs/instagram-api-setup.md](docs/instagram-api-setup.md) — uses the Instagram-Login API (`graph.instagram.com`), which needs **no Facebook Page** and sidesteps the New Pages Experience block.
- **Supabase (memory + checkpointer + image storage):** [docs/supabase-setup.md](docs/supabase-setup.md)

## Stack

- **Orchestration:** LangGraph (Postgres checkpointer via Supabase, else in-memory)
- **Brain:** Claude — Haiku for caption drafts, Sonnet for strategy/review
- **Images:** Google Gemini "Nano Banana" (`gemini-3.1-flash-image`), reference-guided for mascot consistency *(requires billing — not on the free tier)*
- **Publishing:** Instagram Graph API with Instagram Login
- **Memory & storage:** Supabase (pgvector brand memory + public Storage bucket for post images)
- **Observability:** Langfuse (Phase 5+)
- **CI/CD:** GitHub Actions

## Status

Phases 0–6 implemented and wired. First live post published to [@voodoomomo](https://www.instagram.com/voodoomomo/) — the full draft → approval → publish path is proven end-to-end. See [docs/roadmap.md](docs/roadmap.md) for remaining hardening work.
