# Supabase Setup — brand memory + checkpointer

Supabase provides two things to this project:
- **Brand memory** — `brand_profile` (config) and `brand_posts` (published posts + pgvector
  embeddings for semantic retrieval), accessed via the REST client in
  `src/memory/brand_memory.py`.
- **LangGraph checkpointer** — `PostgresSaver` persists graph state, via a direct Postgres
  connection (`SUPABASE_DB_URL`).

---

## Step 1 — Create the project

<https://supabase.com/dashboard> → New project. Free tier is fine (note: it **pauses after
~1 week of inactivity** — just un-pause from the dashboard). Save the **database password**
you set here; you'll need it for `SUPABASE_DB_URL`.

## Step 2 — Get the keys (Settings → API)

Two different keys live here — they are **not** interchangeable:

| Key | Prefix | Use |
|---|---|---|
| `anon` / publishable | `sb_publishable_…` / `eyJ…role":"anon"` | Browser/client side. **Subject to RLS.** |
| **`service_role`** | `eyJ…role":"service_role"` | **Backend agent.** Bypasses RLS. **Never ship to a client or commit.** |

This project's RLS policies grant access to `service_role` only, so the backend **must** use
the service-role key. Put it in `.env` as `SUPABASE_KEY`.

> Sanity check: decode the JWT payload (middle segment) — it must say
> `"role":"service_role"`. An `anon` key will silently fail every write.

## Step 3 — Get the connection string (for the checkpointer)

The connection string moved — it's behind the green **`Connect`** button in the **top bar**
of the dashboard (not under Settings → Database anymore).

`Connect` → choose a mode:

| Mode | Host | Network | Use |
|---|---|---|---|
| Direct connection | `db.<ref>.supabase.co:5432` | **IPv6-only** on free tier | Only if your network has IPv6 |
| **Session pooler** (recommended) | `…pooler.supabase.com:5432` | IPv4 | Reliable from anywhere; good for long-lived connections |
| Transaction pooler | `…pooler.supabase.com:6543` | IPv4 | Serverless/short-lived; no prepared statements |

Copy the **Session pooler** URI into `.env` as `SUPABASE_DB_URL`, replacing `[YOUR-PASSWORD]`
with your DB password — **URL-encoded** (see gotchas below).

## Step 4 — Create the schema

The API keys **cannot create tables** — PostgREST only does row CRUD, never DDL. You need a
direct Postgres connection. Two ways:

- **SQL Editor (simplest):** Dashboard → SQL Editor → New query → paste all of
  [db/schema.sql](../db/schema.sql) → Run.
- **Programmatically:** with `psycopg` (needs `psycopg[binary]` for a bundled libpq) connect
  using `SUPABASE_DB_URL` and execute the file.

Creates: `brand_profile` (+ seed row), `brand_posts` (`vector(1536)`), the
`match_brand_posts` RPC, and RLS policies. Verify in Table Editor.

## Step 5 — Verify

- REST + service-role key: a `select` on `brand_profile` returns the seed row; an
  insert/delete round-trip on `brand_posts` succeeds (proves RLS bypass).
- `SUPABASE_DB_URL`: `psycopg.connect(url)` + `select 1` succeeds.
- RPC: `select proname from pg_proc where proname='match_brand_posts'` returns a row.

---

## `.env` expectations

```
# Supabase — Settings > API
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_KEY=<service_role JWT — NOT the anon key>
# Connect button > Session pooler. Password MUST be URL-encoded.
SUPABASE_DB_URL=postgresql://postgres.<ref>:<url-encoded-pw>@<region>.pooler.supabase.com:5432/postgres
```

`.env` is gitignored and holds real values. `.env.example` holds **empty placeholders only**
and is the git-tracked template. Never put a real key, token, or password in `.env.example`.

---

## Gotchas we hit (don't repeat)

1. **Anon key instead of service-role key.** `sb_publishable_*` is the anon key — RLS blocks
   every backend write *silently* (no error, just no data). Use the `service_role` key.
2. **"Where's the connection string?"** It moved to the **`Connect`** button in the top bar,
   not Settings → Database.
3. **Un-encoded password in `SUPABASE_DB_URL`.** A password with URL-special characters
   breaks the URI. Example: a password like `p@ss^word` produces *two* `@` signs and is
   unparseable. URL-encode it: `@` → `%40`, `^` → `%5E`, `#` → `%23`, `:` → `%3A`, `/` → `%2F`.
4. **Direct host is IPv6-only on free tier.** `db.<ref>.supabase.co` may be unreachable from
   IPv4-only networks — use the **Session pooler** host instead.
5. **API keys can't run DDL.** Expecting `service_role` over REST to `CREATE TABLE` fails —
   PostgREST is CRUD-only. Schema needs a direct Postgres connection.
6. **No local Postgres client.** `psql` absent and `psycopg` had no `libpq` — install
   `psycopg[binary]` (bundles its own libpq).
