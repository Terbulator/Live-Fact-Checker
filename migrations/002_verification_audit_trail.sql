-- Evidence audit trail for stored verifications.
--
-- Apply after 001_supabase_persistence.sql:
--   psql "$SUPABASE_DATABASE_URL" -f migrations/002_verification_audit_trail.sql
--
-- Why this exists
-- ---------------
-- 001 stored only the verdict, reason, primary source and confidence. That is
-- enough to answer a claim again, but not enough to *show your work* again: a
-- replayed verdict came back with no supporting statement and no ranked citation
-- list, so the UI rendered a bare verdict while a freshly retrieved one showed
-- its evidence. Two identical answers looked like they had different evidential
-- support.
--
-- This migration carries the rest of the evidence alongside the verdict, in both
-- the read-through cache and the session history, so a cached replay is as
-- auditable as a live retrieval.
--
--   * supporting_statement -- the evidence-grounded explanation. NULL when no
--     citable evidence was retrieved. Never backfilled or synthesised.
--   * sources -- the ranked, de-duplicated citation list, JSON encoded. Defaults
--     to an empty array so a row written by an older backend still reads cleanly.
--
-- Both are nullable / defaulted so this is a purely additive change: an older
-- application build keeps working against the migrated schema, and a row written
-- before the migration reads as "no extra evidence" rather than failing.
--
-- Failure mode
-- ------------
-- If these columns are absent, the backend's cache writes fail soft (they are
-- already designed never to raise), so the pipeline still verifies correctly and
-- simply stops caching. Nothing is lost silently in a way that changes a verdict.

alter table verification_cache
    add column if not exists supporting_statement text,
    add column if not exists sources jsonb not null default '[]'::jsonb;

alter table session_verifications
    add column if not exists supporting_statement text,
    add column if not exists sources jsonb not null default '[]'::jsonb;

comment on column verification_cache.supporting_statement is
    'Evidence-grounded explanation replayed with the verdict. NULL when no citable evidence was retrieved.';

comment on column verification_cache.sources is
    'Ranked citation list (url/title/snippet/confidence) replayed with the verdict.';

comment on column session_verifications.supporting_statement is
    'Evidence-grounded explanation for this verdict, or NULL when none was produced.';

comment on column session_verifications.sources is
    'Ranked citation list (url/title/snippet/confidence) behind this verdict.';
