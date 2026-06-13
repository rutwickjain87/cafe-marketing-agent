# Cafe Marketing Agent — Project Memory

## Architecture conventions

- All agents are LangGraph nodes defined in `src/graph.py`
- Only `Engagement` runs as a true agentic loop; all others are deterministic nodes
- State machine: `draft → approved → scheduled → published`
- `publish` node is unreachable unless `state["approved"] == True` — this is a hard invariant
- Every agent output includes `confidence_score: float`; below 0.7 → set `human_review_required = True`
- Tool distribution follows least-privilege: publishing tools → Publishing node only; comment/DM tools → Engagement node only

## Brand profile

@docs/brand-voice.md

## Never do (compliance)

- Never call any publish or DM tool unless `approved == True` in state
- Never store credentials, tokens, or PII in logs or LangGraph state
- Never auto-publish Reels with trending audio — route to `manual_publish_queue` instead (Meta API restriction)
- Never initiate a DM; only reply within the 24-hour user-initiated window
- Never retry after a `DM_WINDOW_EXPIRED` error — discard the reply

## Stack decisions

- Supabase pgvector for brand memory (skip Zep until temporal graph is needed)
- Claude Haiku for caption drafts; Claude Sonnet for strategy and review passes
- Composio for MCP tool exposure; register server in Claude Code with `/mcp`
- Langfuse for tracing and eval pass-rate tracking (Phase 5+)

## Phase 0 checklist (current phase)

- [x] Repo skeleton + secret hygiene
- [ ] `~/.claude/CLAUDE.md` personal preferences
- [ ] `src/agents/engagement/CLAUDE.md` DM compliance rules (path-scoped)
- [ ] `.claude/commands/` slash commands wired up
- [ ] `.claude/settings.json` publish/DM tools denied by default
- [ ] `@docs/brand-voice.md` brand voice doc created and imported
