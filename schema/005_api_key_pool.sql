-- 005_api_key_pool.sql
-- Adds the key-pool subsystem: scraped potential keys, validated working keys,
-- the GitHub PAT pool used by the scraper, structured logs for the workers,
-- and an extended system_status row that tracks the active Gemini tier
-- (gemini-2.5-pro -> gemini-3-flash-preview -> gemini-2.5-flash) plus the
-- circuit-breaker cooldown.

begin;

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- potential_keys: raw Gemini keys harvested by the scraper before validation.
-- The scraper writes here; the validator reads pending rows, tests them,
-- and either drops a row in validated_keys or marks the row invalid.
-- ---------------------------------------------------------------------------
create table potential_keys (
    id                uuid        primary key default gen_random_uuid(),
    key_value         text        not null unique,
    source            text        not null check (source in ('github')),
    source_url        text,
    found_at          timestamptz not null default now(),
    metadata          jsonb,
    validation_status text        not null default 'pending'
                                  check (validation_status in (
                                      'pending', 'valid', 'invalid', 'quota_reached', 'quota_exceeded'
                                  )),
    validated_at      timestamptz
);

create index potential_keys_status on potential_keys(validation_status);

-- ---------------------------------------------------------------------------
-- validated_keys: keys the validator has confirmed against the Gemini API.
-- The manager picks rows from here using FOR UPDATE SKIP LOCKED. capabilities
-- holds the JSON list of ModelCapability records produced during validation.
-- ---------------------------------------------------------------------------
create table validated_keys (
    id                       uuid        primary key default gen_random_uuid(),
    potential_key_id         uuid        references potential_keys(id) on delete cascade,
    key_value                text        not null,
    is_valid                 boolean     not null,
    status                   text        not null,
    capabilities             jsonb,
    total_models_accessible  integer,
    total_models_tested      integer,
    average_response_time_ms numeric,
    quota_remaining          integer,
    rate_limit_info          jsonb,
    validated_at             timestamptz not null default now(),
    last_used_at             timestamptz,
    consecutive_failures     integer     not null default 0
);

create index validated_keys_pickable
    on validated_keys (status, last_used_at nulls first)
    where status = 'valid';

-- ---------------------------------------------------------------------------
-- github_tokens: GitHub PAT pool used by the scraper for code-search calls.
-- The scraper rotates tokens on rate-limit and refreshes the cache from this
-- table when the local pool is exhausted.
-- ---------------------------------------------------------------------------
create table github_tokens (
    id                    uuid        primary key default gen_random_uuid(),
    token_name            text        not null,
    token_value           text        not null unique,
    is_active             boolean     not null default true,
    rate_limit_remaining  integer,
    rate_limit_reset_at   timestamptz,
    successful_requests   bigint      not null default 0,
    failed_requests       bigint      not null default 0,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now()
);

create index github_tokens_active_remaining
    on github_tokens (is_active, rate_limit_remaining desc nulls first)
    where is_active = true;

-- Dedicated trigger function for github_tokens so the table is self-contained
-- and the spec line 507-514 contract is preserved verbatim.
create or replace function github_tokens_set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger trg_github_tokens_updated_at
    before update on github_tokens
    for each row execute function github_tokens_set_updated_at();

-- ---------------------------------------------------------------------------
-- key_pool_logs: structured log lines emitted by every key-pool worker
-- (scraper / validator / revalidator / manager). Used by the dashboard
-- to render recent activity per service.
-- ---------------------------------------------------------------------------
create table key_pool_logs (
    id           uuid        primary key default gen_random_uuid(),
    service      text        not null,
    level        text        not null,
    message      text        not null,
    meta         jsonb,
    execution_id uuid,
    created_at   timestamptz not null default now()
);

create index key_pool_logs_recent on key_pool_logs(service, created_at desc);

-- ---------------------------------------------------------------------------
-- system_status: per-service heartbeat plus the gemini_tier_manager tier
-- state. The manager stores active_tier, the per-tier exhaustion timestamps,
-- the recovery probe heartbeat, and the circuit-breaker cooldown in the same
-- row keyed by service='gemini_tier_manager'.
-- ---------------------------------------------------------------------------
create table system_status (
    service                text        primary key,
    state                  text        not null,
    last_execution_id      uuid,
    last_run_at            timestamptz,
    last_stats             jsonb,
    last_error             text,
    last_query_index       integer,
    active_tier            text,
    tier_pro_exhausted_at  timestamptz,
    tier_3_exhausted_at    timestamptz,
    last_recovery_probe_at timestamptz,
    circuit_open_until     timestamptz
);

-- Seed the tier-manager row so the manager can read its state on first boot
-- without a chicken-and-egg insert. Idempotent: re-running the migration
-- against an existing database leaves the live row untouched.
insert into system_status (service, state, active_tier)
values ('gemini_tier_manager', 'active', 'gemini-2.5-pro')
on conflict (service) do nothing;

-- ---------------------------------------------------------------------------
-- Row level security: enable on every key-pool table and add the same
-- authenticated_all policy used by the business tables in 004. The pipeline
-- runs as service_role and bypasses RLS; only the Next.js dashboard ever
-- hits these policies.
-- ---------------------------------------------------------------------------
alter table potential_keys enable row level security;
alter table validated_keys enable row level security;
alter table github_tokens  enable row level security;
alter table key_pool_logs  enable row level security;
alter table system_status  enable row level security;

create policy authenticated_all on potential_keys
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on validated_keys
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on github_tokens
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on key_pool_logs
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on system_status
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

commit;
