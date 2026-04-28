-- 004_supabase_migration.sql
-- Ports the existing 9 business tables (campaigns, companies, contacts,
-- emails, contact_campaigns, company_campaigns, contact_campaign_links,
-- settings, sender_accounts) plus the dpp_fit_reasoning column to a
-- Supabase-friendly form. All tables stay in the public schema and
-- enable row level security with a single authenticated_all policy.

begin;

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Shared trigger function: auto-update updated_at on every UPDATE.
-- Defined once and reused by every table that owns an updated_at column.
-- ---------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- 1. campaigns
-- ---------------------------------------------------------------------------
create table campaigns (
    id                 uuid        primary key default gen_random_uuid(),
    name               text        not null unique,
    target_description text        not null default '',
    status             text        not null default 'Active'
                                   check (status in ('Active', 'Paused', 'Completed', 'Abort')),
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

create trigger trg_campaigns_updated_at
    before update on campaigns
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- 2. companies (with dpp_fit_reasoning column rolled in from 003)
-- ---------------------------------------------------------------------------
create table companies (
    id                uuid        primary key default gen_random_uuid(),
    name              text        not null,
    website           text,
    industry          text        check (industry in ('Fashion', 'Streetwear', 'Lifestyle', 'Other')),
    location          text,
    size              text,
    dpp_fit_score     integer,
    dpp_fit_reasoning text,
    status            text        not null default 'Discovered'
                                  check (status in ('Discovered', 'Enriched', 'Partially Enriched', 'Contacts Found')),
    source_query      text,
    body              text        not null default '',
    last_enriched_at  timestamptz,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create trigger trg_companies_updated_at
    before update on companies
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- 3. contacts
-- ---------------------------------------------------------------------------
create table contacts (
    id             uuid        primary key default gen_random_uuid(),
    name           text        not null,
    job_title      text,
    email          text,
    email_verified boolean     not null default false,
    linkedin_url   text,
    company_id     uuid        references companies(id) on delete set null,
    status         text        not null default 'Found'
                               check (status in ('Found', 'Enriched', 'Researched', 'Email Generated')),
    context        text,
    body           text        not null default '',
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

create trigger trg_contacts_updated_at
    before update on contacts
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- 4. emails
-- ---------------------------------------------------------------------------
create table emails (
    id             uuid        primary key default gen_random_uuid(),
    subject        text        not null,
    contact_id     uuid        references contacts(id) on delete set null,
    campaign_id    uuid        references campaigns(id) on delete set null,
    status         text        not null default 'Pending Review'
                               check (status in ('Pending Review', 'Approved', 'Sent', 'Rejected', 'Failed')),
    sender_address text,
    body           text        not null default '',
    bounce         boolean     not null default false,
    sent_at        timestamptz,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

create trigger trg_emails_updated_at
    before update on emails
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- 5. contact_campaigns (denormalized junction)
-- ---------------------------------------------------------------------------
create table contact_campaigns (
    id                   uuid        primary key default gen_random_uuid(),
    contact_id           uuid        not null references contacts(id) on delete cascade,
    campaign_id          uuid        not null references campaigns(id) on delete cascade,
    company_id           uuid        references companies(id) on delete set null,
    name                 text        not null,
    job_title            text,
    company_name         text,
    email                text,
    email_verified       boolean     not null default false,
    linkedin_url         text,
    industry             text,
    location             text,
    company_fit_score    real,
    relevance_score      real,
    score_reasoning      text,
    personalized_context text,
    context              text,
    email_subject        text,
    outreach_status      text        not null default 'New'
                                     check (outreach_status in (
                                         'New', 'Email Pending Review', 'Email Approved',
                                         'Sent', 'Replied', 'Meeting Booked'
                                     )),
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now(),
    unique (contact_id, campaign_id)
);

create trigger trg_contact_campaigns_updated_at
    before update on contact_campaigns
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- 6. company_campaigns (many-to-many join)
-- ---------------------------------------------------------------------------
create table company_campaigns (
    company_id  uuid references companies(id) on delete cascade,
    campaign_id uuid references campaigns(id) on delete cascade,
    primary key (company_id, campaign_id)
);

-- ---------------------------------------------------------------------------
-- 7. contact_campaign_links (many-to-many join)
-- ---------------------------------------------------------------------------
create table contact_campaign_links (
    contact_id  uuid references contacts(id) on delete cascade,
    campaign_id uuid references campaigns(id) on delete cascade,
    primary key (contact_id, campaign_id)
);

-- ---------------------------------------------------------------------------
-- 8. settings (key/value config)
-- ---------------------------------------------------------------------------
create table settings (
    key        text        primary key,
    value      text        not null,
    updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 9. sender_accounts (SMTP sender pool, used by web/settings)
-- ---------------------------------------------------------------------------
create table sender_accounts (
    id          uuid        primary key default gen_random_uuid(),
    email       text        not null unique,
    password    text        not null,
    daily_limit integer     not null default 10,
    is_active   boolean     not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create trigger trg_sender_accounts_updated_at
    before update on sender_accounts
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- Indexes (mirror 001_init.sql)
-- ---------------------------------------------------------------------------
create index idx_companies_status            on companies(status);
create index idx_companies_name              on companies(name);
create index idx_companies_last_enriched     on companies(last_enriched_at);
create index idx_contacts_status             on contacts(status);
create index idx_contacts_email              on contacts(email);
create index idx_contacts_company            on contacts(company_id);
create index idx_emails_status               on emails(status);
create index idx_emails_campaign             on emails(campaign_id);
create index idx_contact_campaigns_campaign  on contact_campaigns(campaign_id);
create index idx_contact_campaigns_contact   on contact_campaigns(contact_id);
create index idx_contact_campaigns_scores    on contact_campaigns(relevance_score, company_fit_score);

-- ---------------------------------------------------------------------------
-- Row level security: enable on every business table and add a single
-- authenticated_all policy. The pipeline runs as service_role so it
-- bypasses RLS; only the Next.js dashboard hits these policies.
-- ---------------------------------------------------------------------------
alter table campaigns              enable row level security;
alter table companies              enable row level security;
alter table contacts               enable row level security;
alter table emails                 enable row level security;
alter table contact_campaigns      enable row level security;
alter table company_campaigns      enable row level security;
alter table contact_campaign_links enable row level security;
alter table settings               enable row level security;
alter table sender_accounts        enable row level security;

create policy authenticated_all on campaigns
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on companies
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on contacts
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on emails
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on contact_campaigns
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on company_campaigns
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on contact_campaign_links
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on settings
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

create policy authenticated_all on sender_accounts
    for all
    using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

commit;
