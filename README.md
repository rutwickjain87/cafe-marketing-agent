# Cafe Marketing Agent

AI-powered Instagram/Facebook marketing automation for independent cafes. Built with LangGraph + Claude.

Doubles as study for the **Claude Certified Architect – Foundations (CCA-F)** exam — each phase maps to a specific exam domain. See [`schedule.md`](./schedule.md) for the full roadmap.

## Architecture

```
Coordinator
  ├── Strategy    (calendar, goals)
  ├── Creative    (captions, hashtags, assets)
  ├── [human approval gate]
  ├── Publishing  (Meta Graph API)
  ├── Engagement  (comments + DMs — only true agent)
  └── Analytics   (insights, reporting)
```

## Quick start

```bash
cp .env.example .env
# fill in .env values
pip install -r requirements.txt
python -m src.graph
```

## Phases

| Phase | Focus | Exam domain | Hours |
|---|---|---|---|
| 0 | Claude Code setup | Domain 3 (20%) | ~10 |
| 1 | Caption generator MVP | Domain 4 (20%) | ~14 |
| 2 | Meta API tool layer | Domain 2 (18%) | ~24 |
| 3 | Multi-agent orchestration | Domain 1 (27%) | ~36 |
| 4 | Context & reliability | Domain 5 (15%) | ~20 |
| 5 | Prompt/output hardening | Domain 4 | ~14 |
| 6 | CI/CD + automation | Domain 3 | ~12 |

## Stack

- **Orchestration:** LangGraph
- **Brain:** Anthropic Claude (Haiku for drafts, Sonnet for review)
- **Persistence:** Supabase (state + pgvector memory)
- **Integrations:** Composio (MCP), Meta Graph API
- **Observability:** Langfuse
- **CI/CD:** GitHub Actions
