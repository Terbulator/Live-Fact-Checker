-- Persistent fact-check cache and session history for the Live Fact-Checker.
--
-- Apply with psql, or paste into the Supabase SQL editor:
--   psql "$SUPABASE_DATABASE_URL" -f migrations/001_supabase_persistence.sql
--
-- Design notes
-- ------------
-- * verification_cache holds ONLY verdicts produced by real retrieval through
--   the search provider. The application disables the cache entirely in mock
--   mode and whenever the claim engine is not strict, so no mock or
--   rule-based answer can ever reach this table. See
--   backend/persistence/store.py for the guard.
-- * Entries carry an absolute expires_at rather than a TTL applied on read, so
--   expiry needs no background job and a stale row can never be served.
-- * Row Level Security is enabled with no policies. That denies the PostgREST
--   `anon` and `authenticated` roles outright, which matters because Supabase
--   exposes every table through PostgREST using the project anon key. The
--   backend connects with the service-role connection string, which bypasses
--   RLS, so application behaviour is unaffected.

create table if not exists verification_cache (
    claim_key      text primary key,
    verdict        text        not null,
    reason         text        not null,
    source         text        not null,
    confidence     double precision,
    provider       text        not null,
    session_id     text,
    created_at     timestamptz not null default now(),
    last_used_at   timestamptz not null default now(),
    expires_at     timestamptz not null,
    hit_count      bigint      not null default 0,

    constraint verification_cache_verdict_check
        check (verdict in ('TRUE', 'FALSE', 'UNVERIFIABLE', 'AMBIGUOUS'))
);

-- Supports the expiry sweep that keeps the table from growing without bound.
create index if not exists verification_cache_expires_at_idx
    on verification_cache (expires_at);


create table if not exists sessions (
    session_id         text primary key,
    status             text        not null,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    ended_at           timestamptz,
    transcript_count   integer     not null default 0,
    claim_count        integer     not null default 0,
    verification_count integer     not null default 0,
    error_count        integer     not null default 0
);

create index if not exists sessions_created_at_idx
    on sessions (created_at desc);


create table if not exists session_claims (
    claim_id    text primary key,
    session_id  text             not null
                            references sessions (session_id) on delete cascade,
    speaker     text,
    timestamp   double precision,
    claim       text             not null,
    claim_type  text,
    created_at  timestamptz      not null default now()
);

create index if not exists session_claims_session_id_idx
    on session_claims (session_id);


create table if not exists session_verifications (
    claim_id    text primary key,
    session_id  text             not null
                            references sessions (session_id) on delete cascade,
    verdict     text             not null,
    reason      text             not null,
    source      text,
    confidence  double precision,
    -- Whether this verdict was served from the persistent cache rather than
    -- freshly retrieved, so stored history never misrepresents its provenance.
    from_cache  boolean          not null default false,
    created_at  timestamptz      not null default now(),

    constraint session_verifications_verdict_check
        check (verdict in ('TRUE', 'FALSE', 'UNVERIFIABLE', 'AMBIGUOUS'))
);

create index if not exists session_verifications_session_id_idx
    on session_verifications (session_id);


alter table verification_cache      enable row level security;
alter table sessions                enable row level security;
alter table session_claims          enable row level security;
alter table session_verifications  enable row level security;
