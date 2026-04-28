-- 006_views.sql
-- SQL views consumed by the Next.js dashboard via the Supabase typed
-- builder. The original queries.ts used tagged-template SQL with joins,
-- aggregates, and window functions that the Supabase JS builder cannot
-- express directly. Each view encapsulates one of those queries so the
-- dashboard can `select * from <view>` instead of writing raw SQL.

begin;

-- ---------------------------------------------------------------------------
-- campaigns_with_counts -- adds company_count and contact_count for the
-- dashboard table on `/`.
-- ---------------------------------------------------------------------------
create or replace view campaigns_with_counts as
select
    c.*,
    coalesce(cc_co.cnt, 0)::int as company_count,
    coalesce(cc_ct.cnt, 0)::int as contact_count
from campaigns c
left join (
    select campaign_id, count(*) as cnt
    from company_campaigns
    group by campaign_id
) cc_co on cc_co.campaign_id = c.id
left join (
    select campaign_id, count(*) as cnt
    from contact_campaign_links
    group by campaign_id
) cc_ct on cc_ct.campaign_id = c.id;

-- ---------------------------------------------------------------------------
-- companies_with_campaigns -- companies with the array_agg of linked
-- campaign names. Powers the global /companies page.
-- ---------------------------------------------------------------------------
create or replace view companies_with_campaigns as
select
    c.*,
    array_agg(distinct camp.name) filter (where camp.name is not null) as campaign_names
from companies c
left join company_campaigns cc on c.id = cc.company_id
left join campaigns camp on cc.campaign_id = camp.id
group by c.id;

-- ---------------------------------------------------------------------------
-- contacts_with_company -- contacts joined to their company name. Powers
-- /contacts and /campaigns/[id]/contacts.
-- ---------------------------------------------------------------------------
create or replace view contacts_with_company as
select
    ct.*,
    co.name as company_name
from contacts ct
left join companies co on ct.company_id = co.id;

-- ---------------------------------------------------------------------------
-- emails_with_contacts -- emails joined with contact + company info.
-- Powers /emails and /campaigns/[id]/emails.
-- ---------------------------------------------------------------------------
create or replace view emails_with_contacts as
select
    e.id,
    e.subject,
    e.body,
    e.status,
    e.created_at,
    e.contact_id,
    e.campaign_id,
    ct.name      as contact_name,
    ct.email     as contact_email,
    ct.job_title as contact_job_title,
    co.name      as company_name,
    co.website   as company_website
from emails e
left join contacts ct on ct.id = e.contact_id
left join companies co on co.id = ct.company_id;

-- ---------------------------------------------------------------------------
-- leads_full -- contact_campaigns enriched with company URL, email body,
-- and campaign name. Powers /leads and /campaigns/[id]/leads.
-- ---------------------------------------------------------------------------
create or replace view leads_full as
select
    cc.id,
    cc.name,
    cc.job_title,
    cc.company_name,
    cc.email,
    cc.linkedin_url,
    cc.company_fit_score,
    cc.relevance_score,
    cc.outreach_status,
    cc.email_subject,
    cc.campaign_id,
    cc.contact_id,
    cc.company_id,
    cc.score_reasoning,
    cc.context,
    cc.personalized_context,
    cc.created_at,
    c.name     as campaign_name,
    co.website as company_url,
    e.body     as email_body
from contact_campaigns cc
left join campaigns c on c.id = cc.campaign_id
left join companies co on co.id = cc.company_id
left join emails e
    on e.contact_id = cc.contact_id
   and e.campaign_id = cc.campaign_id;

-- ---------------------------------------------------------------------------
-- campaign_email_timeline -- daily cumulative email counts per campaign,
-- used by the dashboard line chart. Window function -> view.
-- ---------------------------------------------------------------------------
create or replace view campaign_email_timeline as
select
    c.id   as campaign_id,
    c.name as campaign_name,
    e.day,
    e.daily_count,
    sum(e.daily_count) over (
        partition by c.id order by e.day
        rows between unbounded preceding and current row
    )::int as cumulative
from campaigns c
join (
    select
        campaign_id,
        date_trunc('day', created_at)::date as day,
        count(*)::int as daily_count
    from emails
    group by campaign_id, date_trunc('day', created_at)::date
) e on e.campaign_id = c.id;

commit;
