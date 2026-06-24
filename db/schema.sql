-- Voodoo Momo — Supabase pgvector schema
-- Run once in the Supabase SQL editor (Database > SQL Editor > New query)

-- Enable the vector extension (already on in Supabase; harmless if run twice)
create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- brand_profile: single-row config doc, edited in Supabase Dashboard
-- ---------------------------------------------------------------------------
create table if not exists brand_profile (
  id           serial primary key,
  name         text not null default 'Voodoo Momo',
  instagram    text not null default '@voodoomomo',
  tagline      text,
  tone         text,
  core_hashtags jsonb,
  banned_phrases jsonb,
  updated_at   timestamptz default now()
);

insert into brand_profile (name, instagram, tagline, tone, core_hashtags, banned_phrases)
values (
  'Voodoo Momo', '@voodoomomo', 'Taste the Himalayan Magic!',
  'warm, fun, street-style',
  '["#VoodooMomo","#PuneSpecialtyMomo","#WagholiEats"]',
  '["best momos","you deserve","indulge yourself","game-changer","life-changing","mind-blowing"]'
)
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- brand_posts: published posts with embeddings for semantic retrieval
-- ---------------------------------------------------------------------------
create table if not exists brand_posts (
  id           uuid primary key default gen_random_uuid(),
  post_id      text,            -- stable PostAsset id; the publish idempotency key
  media_id     text unique,
  caption      text not null,
  pillar       text,
  format       text,
  permalink    text,
  metrics      jsonb,           -- reach, impressions, likes… (learning loop)
  published_at timestamptz default now(),
  embedding    vector(1536),
  raw          jsonb
);

-- Migrations for existing deployments (safe to re-run)
alter table brand_posts add column if not exists post_id    text;
alter table brand_posts add column if not exists format     text;
alter table brand_posts add column if not exists permalink  text;
alter table brand_posts add column if not exists metrics    jsonb;
alter table brand_posts add column if not exists media_type text default 'image';
alter table brand_posts add column if not exists video_url  text;

-- Idempotency: one published row per post_id. A second publish of the same
-- post_id is rejected at the DB, not just in app code.
create unique index if not exists brand_posts_post_id_key on brand_posts(post_id);

-- IVFFlat index — build after ~100 rows are in the table
-- create index on brand_posts using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- ---------------------------------------------------------------------------
-- scheduled_posts: holding queue for approved, future-dated posts.
-- POST /scheduled/dispatch reads due rows and publishes them exactly once.
-- ---------------------------------------------------------------------------
create table if not exists scheduled_posts (
  post_id      text primary key,   -- stable PostAsset id; dispatch is idempotent on this
  campaign_id  text,
  thread_id    text,               -- originating graph run (for tracing)
  scheduled_at timestamptz,
  status       text default 'scheduled',  -- scheduled | dispatched
  asset        jsonb not null,     -- full serialized PostAsset
  created_at   timestamptz default now()
);

create index if not exists scheduled_posts_due_idx
  on scheduled_posts (status, scheduled_at);

-- ---------------------------------------------------------------------------
-- match_brand_posts: RPC used by src/memory/brand_memory.py
-- ---------------------------------------------------------------------------
create or replace function match_brand_posts(
  query_embedding vector(1536),
  match_count     int default 5
)
returns table (
  id           uuid,
  caption      text,
  pillar       text,
  published_at timestamptz,
  similarity   float
)
language sql stable
as $$
  select id, caption, pillar, published_at,
         1 - (embedding <=> query_embedding) as similarity
  from brand_posts
  order by embedding <=> query_embedding
  limit match_count;
$$;

-- ---------------------------------------------------------------------------
-- Row-level security: service-role key bypasses; anon key blocked
-- ---------------------------------------------------------------------------
alter table brand_profile   enable row level security;
alter table brand_posts     enable row level security;
alter table scheduled_posts enable row level security;

-- drop-then-create so this block is re-runnable (Postgres has no
-- `create policy if not exists`); a half-applied schema otherwise rolls back
-- the whole file when run as one transaction.
drop policy if exists "service role full access" on brand_profile;
create policy "service role full access" on brand_profile
  using (auth.role() = 'service_role');
drop policy if exists "service role full access" on brand_posts;
create policy "service role full access" on brand_posts
  using (auth.role() = 'service_role');
drop policy if exists "service role full access" on scheduled_posts;
create policy "service role full access" on scheduled_posts
  using (auth.role() = 'service_role');
