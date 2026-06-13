# Cafe Marketing Agent → CCA-F Exam Prep Roadmap

A single build that doubles as study for all five competency areas of the Claude Certified Architect – Foundations exam (60 questions). Each phase produces a working improvement to the agent **and** drills a specific exam domain.

**The central move:** build the agent *inside Claude Code* on your existing stack. Your dev environment then exercises Domain 3 every day instead of being crammed separately. The agent's runtime architecture covers the other four.

> **Status (2026-06-14):** Phases 0–6 implemented; first live Instagram post published. Two deltas from this roadmap as written: publishing uses the **Instagram-Login API** (`graph.instagram.com`, no Facebook Page) rather than the Facebook-Login Graph API, and an **image-generation node** (Google Gemini "Nano Banana", reference-guided by the mascot) was added to the Creative step. See [build-schedule.md](build-schedule.md) for the full progress log.

---

## Exam coverage at a glance

| Domain | Weight | Primary phase(s) | Reinforced in |
|---|---|---|---|
| 1. Agentic Architecture & Orchestration | 27% | Phase 3 | Phases 4, 6 |
| 2. Tool Design & MCP Integration | 18% | Phase 2 | Phase 3 |
| 3. Claude Code Configuration & Workflows | 20% | Phase 0 | Every phase (build env) + Phase 6 |
| 4. Prompt Engineering & Structured Output | 20% | Phase 1 | Phase 5 |
| 5. Context Management & Reliability | 15% | Phase 4 | Phases 3, 5 |

Spend the most deliberate effort on **Domain 1 (27%)** and **Domain 3 (20%, your gap)**. Domains 2/4/5 get covered thoroughly but need less standalone study.

---

## Guiding principles

1. **Build in Claude Code.** Use `claude` as the harness to write the agent. Every CLAUDE.md, slash command, plan-mode session, and permission rule you configure is a Domain 3 rep.
2. **Start basic, layer up.** Phase 1 is a single node. Don't orchestrate before you have one good agent.
3. **Turn the real platform constraints into design exercises.** The Meta API limits from our earlier discussion aren't obstacles here — they're perfect exam-relevant design problems:
   - The **24-hour DM window / user-initiated-only** rule → a *workflow enforcement* and *tool boundary* exercise (Domains 1 & 2).
   - **App Review** (skip it via Development mode for one cafe) → a deployment/config concern.
   - **Trending-audio Reels can't auto-publish via API** → an *error-propagation / graceful-degradation* exercise (Domain 5): the agent must route those to a manual-publish queue instead of failing the run.

---

## Phase 0 — Set up the build environment in Claude Code

**Domain 3 (20%) — the whole point of this phase.** · **Effort: ~10 hrs** (higher than its size because it's your weakest domain; the learning curve is the cost, not the typing.)

Build:
- **Project memory** `./CLAUDE.md` at repo root: architecture conventions, the brand profile, the "never do" list (compliance rules, banned phrasing). This is team-shared, source-controlled.
- **User memory** `~/.claude/CLAUDE.md`: your personal coding/style preferences across projects.
- **Path-specific (nested) rules:** put a `CLAUDE.md` inside `agents/engagement/` containing the DM-compliance rules. Confirm it only loads when Claude touches files in that subtree — this *is* the glob-scoping / context-fork behavior the exam probes.
- **Imports:** use `@path` syntax in the root CLAUDE.md to pull in `@docs/brand-voice.md`, etc.
- **Custom slash commands / skills:** `/new-campaign`, `/draft-caption`, `/weekly-report` under `.claude/commands/` (or `.claude/skills/<name>/SKILL.md`). Use `$ARGUMENTS` and `` !`cmd` `` substitution in at least one.
- **Permissions** in `settings.json`: deny any publish/DM tool by default (`ask` rule), so nothing posts without your approval. Doubles as your compliance guardrail.

Concepts to practice: CLAUDE.md hierarchy & precedence, imports, nested/path-scoped memory, custom commands vs skills (and which wins on name clash), `/init`, `/memory`, `/context`, `/compact`, `/permissions`, plan mode (`/plan` or Shift+Tab) before any large refactor.

Definition of done: you can explain, from your own setup, what loads when, in what precedence order, and why a rule in `agents/engagement/CLAUDE.md` does not pollute context during unrelated work.

---

## Phase 1 — Single-agent MVP: the caption + hashtag generator

**Domain 4 (20%) primary; light Domain 2.** · **Effort: ~14 hrs**

Build one LangGraph node: input a post brief (product, goal, format) → output `{caption, hashtags[], cta, confidence}` as validated JSON.

Concepts to practice:
- **Explicit criteria** in the prompt: brand voice, length cap, CTA requirement, hashtag count, banned words.
- **Few-shot**: 2–3 good captions and 1–2 deliberately bad ones (off-brand, too long) so the model learns the boundary.
- **Structured output**: enforce a JSON schema (Pydantic or response schema). No prose, schema only.
- **Validation + retry loop**: if output fails schema *or* violates a rule (e.g., contains a banned phrase), feed the error back and retry with a repair prompt; cap retries.

Definition of done: malformed or off-brand output is caught and repaired automatically, not surfaced to you.

---

## Phase 2 — Tool design: wrap the Meta Graph API as tools

**Domain 2 (18%) primary.** · **Effort: ~24 hrs** (OAuth/token handling, the container publish model, and the error taxonomy are the time sinks.)

Build a clean tool layer over the publishing/engagement/insights endpoints.

Concepts to practice:
- **Clear boundaries:** one job per tool — `create_media_container`, `poll_container_status`, `publish_media`, `reply_to_comment`, `get_media_insights`. Typed inputs/outputs.
- **Structured error responses:** map Meta's real failure modes to typed errors the agent can reason about — `RATE_LIMITED`, `PAGE_PUBLISH_AUTH_REQUIRED`, `DM_WINDOW_EXPIRED`, `AUDIO_UNAVAILABLE`. Each carries a recommended recovery action, not just a message.
- **MCP integration:** expose the tool layer as an MCP server (or wire one via Composio), then register it in Claude Code with `/mcp`. This is the same MCP concept the exam tests, practiced on both sides (building and consuming).
- **Tool distribution / least privilege:** decide which subagent gets which tools — publishing tools never go to the analytics agent; the engagement agent gets comment/DM tools only.

Definition of done: a tool failure returns a structured error the agent acts on (retry, defer, escalate), and no agent holds a tool it shouldn't.

---

## Phase 3 — Multi-agent orchestration: coordinator + subagents

**Domain 1 (27%) — your heaviest phase.** · **Effort: ~36 hrs** (the largest block; this is where the exam weight and the build weight both peak.)

Build a coordinator that takes "run this week's marketing" and decomposes it across subagents: Strategy → Creative → (human approval) → Publishing → Engagement → Analytics.

Concepts to practice:
- **Coordinator–subagent pattern:** coordinator owns the goal and ordering; subagents own narrow jobs with isolated context.
- **Task decomposition:** break the goal into ordered subtasks with dependencies (Creative can't run before Strategy fixes the calendar).
- **Agentic loop:** plan → act → observe → re-plan when a step fails.
- **Session state:** track draft/approved/scheduled/published status across the run in LangGraph state, persisted to Supabase so a crash mid-run resumes cleanly.
- **Workflow enforcement:** the human-approval gate as an *enforced* state transition — `publish` is unreachable unless `approved == true`. This is both an orchestration concept and your safety guardrail.

Design honesty (also a likely exam distinction): not every box is a true "agent." Strategy/Creative/Publishing/Analytics are mostly deterministic nodes; only **Engagement** (triaging unpredictable DMs/comments) genuinely needs agentic autonomy. Knowing when *not* to use an agent is part of the competency.

Definition of done: one command runs the full week end-to-end with the approval gate enforced and state that survives a restart.

---

## Phase 4 — Context management & reliability

**Domain 5 (15%) primary.** · **Effort: ~20 hrs**

Harden the agent against long-horizon and failure conditions.

Concepts to practice:
- **Preserve critical info across long interactions:** store brand voice, past posts, and what performed in **Zep / Supabase pgvector**; retrieve into every generation so identity persists beyond any single context window.
- **Escalation patterns:** Engagement subagent escalates to you when a DM is a complaint, a high-value booking, or ambiguous intent — define the triggers explicitly.
- **Error propagation:** decide how a downstream failure travels. The trending-audio Reel that can't auto-publish should *degrade gracefully* into a manual-publish queue with a notification, not abort the whole weekly run.
- **Confidence calibration:** every draft/reply carries a confidence score; below threshold → route to human review instead of acting. This is the exam's "handle uncertainty with confidence calibration," made concrete.

Definition of done: a single failing step degrades locally; low-confidence outputs self-route to you; brand voice stays consistent across a simulated month of runs.

---

## Phase 5 — Prompt & structured-output hardening

**Domain 4 (20%) reinforced.** · **Effort: ~14 hrs**

A dedicated pass once the system works.

Concepts to practice: a few-shot library per content type; a JSON schema for the *entire* 30-day calendar object (not just one caption); repair prompts for validation failures; a small **eval harness** (does each caption meet its criteria?) traced in **Langfuse** so you can see pass rates and prompt regressions.

Definition of done: you can change a prompt and immediately see whether eval pass-rate moved.

---

## Phase 6 — CI/CD + Claude Code in automation

**Domain 3 (20%) reinforced — plays to your DevSecOps strength.** · **Effort: ~12 hrs** (fast for you given your GitHub Actions background.)

Build:
- A **GitHub Actions** workflow that runs Claude Code headless on PRs to review prompt/tool changes, run the Phase 5 eval suite, and run `/security-review` on the tool layer.
- A scheduled trigger (GH Actions cron or your Hetzner VPS) that kicks off the weekly run.

Concepts to practice: Claude Code in non-interactive/CI contexts, headless invocation, gating merges on eval results.

Definition of done: a prompt change that lowers eval pass-rate fails the PR check.

---

## Effort summary

| Phase | Hours |
|---|---|
| 0 — Claude Code setup | ~10 |
| 1 — Caption generator | ~14 |
| 2 — Meta API tool layer | ~24 |
| 3 — Multi-agent orchestration | ~36 |
| 4 — Context & reliability | ~20 |
| 5 — Prompt/output hardening | ~14 |
| 6 — CI/CD + automation | ~12 |
| Production hardening (secrets, deploy, monitoring, cutover) | ~10 |
| **Total** | **~140 hrs** |

## 4-week plan (full production deploy)

Compressing all phases into 4 weeks means **~35 hrs/week** — effectively full-time. Be honest with yourself about whether that fits alongside consulting. If you can only commit ~20 hrs/week, the *deployable* system (Phases 0–3, ~84 hrs) still lands in ~3 weeks; Phases 4–6 then harden it over the following weeks. The schedule below assumes you can hit ~35 hrs/week.

- **Week 1 (~35 hrs):** Phase 0 (10) + Phase 1 (14) + start Phase 2 (11). *Domains 3 + 4 underway immediately.*
- **Week 2 (~35 hrs):** finish Phase 2 (13) + first half of Phase 3 (22). *Domain 2 done; Domain 1 — the big one — begins.*
- **Week 3 (~36 hrs):** finish Phase 3 (14) + Phase 4 (20) + start Phase 5 (2). *Domain 1 complete; Domain 5 done.*
- **Week 4 (~34 hrs):** finish Phase 5 (12) + Phase 6 (12) + production hardening & cutover (10). *Live in production; then run the reverse-index review before the exam.*

Sequencing rule that protects both goals: never start orchestration (Phase 3) before Phase 1's single node is solid, and do Phase 0 first so every later phase compounds your Domain 3 reps.

---

## Tooling: free vs paid (per month, as of June 2026)

Two cost buckets matter and people conflate them: the **dev environment** you use to *build* the agent (Claude Code), and the **runtime stack** the agent *runs on* in production. Almost everything else has a free tier that comfortably covers a single cafe.

| Tool | Role | Free tier enough? | Paid tier (USD/mo) |
|---|---|---|---|
| **Claude Code** (dev env) | Building the agent | No — requires a paid Claude plan | **Pro $20/mo** ($17 annual) includes Claude Code; Max $100/$200 only if you build Opus-heavy all day |
| **Anthropic API** (runtime brain) | Agent's live generation/replies | No permanent free tier (trial credits only) | Pay-per-token: Haiku $1/$5, Sonnet $3/$15, Opus $5/$25 per MTok. One cafe ≈ **~$5–15/mo** |
| **LangGraph** | Orchestration | Yes — open-source, self-host | $0 |
| **Supabase** (state + pgvector) | Persistence, vector memory | Free tier *pauses after 1 week idle* — not for production | **Pro $25/mo** (pgvector included free on every tier) |
| **Composio** | MCP / integrations | Yes — 20K tool calls/mo covers one cafe | $29/mo (200K calls) if you outgrow it |
| **Langfuse** | Tracing / evals | Yes — Hobby 50K units/mo is plenty | Core $29/mo; or self-host (MIT) free |
| **Zep** | Temporal memory | Free 10K messages, or skip it | Pro **$99/mo** — but see note below |
| **Browserbase** | Competitor/trend research only | Free 1 browser-hr + 1K fetch calls | Developer $20/mo (skip for v1) |
| **E2B** | Sandbox (optional) | Yes (skip for v1 unless media processing) | usage-based |
| **Meta Graph API** | Publishing / engagement | Free (only cost is ad spend, if any) | $0 |
| **GitHub Actions** | CI/CD | Yes — free minutes cover this | $0 |

**Minimum realistic monthly cost for a production single-cafe deployment: ~$50–60/mo** — Claude Pro ($20) + Anthropic API runtime (~$5–15) + Supabase Pro ($25), with everything else on free tiers.

Two cost-savers worth taking:
- **Skip Zep's $99/mo to start.** You already pay for Supabase pgvector — use it for brand memory in Phase 4. Add Zep only if you later need its temporal knowledge-graph features, or self-host its open-source Graphiti engine for free.
- **Supabase Pro is the one near-unavoidable infra cost** — the free tier's idle-pausing disqualifies it for anything customer-facing. Everything else genuinely runs free at one-cafe volume.

When you productize across multiple cafes, the variable costs (API tokens, Composio calls, Langfuse units, browser hours) scale with client count, and Supabase Pro is per-project — that's where the per-client unit economics for your Digital Employees pricing come from.

---

## Pre-exam reverse index (map each topic to something you built)

Use this in the final days — for every exam concept, you should be able to point at a concrete thing in your repo.

- **Agentic loops / coordinator-subagent / task decomposition / session state / workflow enforcement** → Phase 3.
- **Tool interfaces & boundaries / structured error responses / MCP servers / tool distribution** → Phase 2.
- **CLAUDE.md hierarchy / custom slash commands / path-specific rules / plan mode / CI/CD** → Phase 0 + Phase 6.
- **Explicit criteria / few-shot / JSON-schema output / validation & retry** → Phase 1 + Phase 5.
- **Preserve info across long interactions / escalation / error propagation / confidence calibration** → Phase 4.

Verify Domain 3 details against the official Claude Code docs map before the exam: https://docs.anthropic.com/en/docs/claude-code/claude_code_docs_map.md — config surfaces change version to version, and the exam tracks current behavior.
