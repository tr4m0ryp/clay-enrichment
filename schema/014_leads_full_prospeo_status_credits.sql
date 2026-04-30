-- 014_leads_full_prospeo_status_credits.sql
-- Tighten the prospeo_status logic in leads_full so 0-credit NO_MATCH
-- log rows don't get classified as "found".
--
-- Background: schema 013 marked a contact as 'found' whenever any
-- prospeo_usage row existed for it. After we started logging
-- NO_MATCH calls (with credits=0) for dashboard call-counting, that
-- rule classified misses as found too. We now require credits > 0
-- for 'found', and treat 0-credit log rows as the canonical
-- 'not_found' signal.

BEGIN;

DROP VIEW IF EXISTS leads_full;

CREATE VIEW leads_full AS
SELECT
    cc.id,
    cc.name,
    cc.job_title,
    cc.company_name,
    cc.email,
    cc.email_verified,
    cc.linkedin_url,
    cc.phone,
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
    -- Prospeo check status:
    --   'found'     -- a credit-spending match was logged
    --                  (prospeo_usage row with credits > 0)
    --   'not_found' -- Prospeo was queried and either:
    --                    (a) returned NO_MATCH (logged with credits=0),
    --                    or
    --                    (b) the resolver touched the row pre-logging
    --                        (updated_at > created_at + 1s, no log row)
    --   'pending'   -- resolver hasn't reached this contact yet
    CASE
        WHEN EXISTS (
            SELECT 1 FROM prospeo_usage pu
            WHERE pu.contact_id = cc.contact_id
              AND pu.credits > 0
        ) THEN 'found'
        WHEN EXISTS (
            SELECT 1 FROM prospeo_usage pu
            WHERE pu.contact_id = cc.contact_id
        ) THEN 'not_found'
        WHEN cc.updated_at > cc.created_at + interval '1 second'
            THEN 'not_found'
        ELSE 'pending'
    END AS prospeo_status,
    c.name     AS campaign_name,
    co.website AS company_url,
    e.body     AS email_body
FROM contact_campaigns cc
LEFT JOIN campaigns c ON c.id = cc.campaign_id
LEFT JOIN companies co ON co.id = cc.company_id
LEFT JOIN emails e
    ON e.contact_id = cc.contact_id
   AND e.campaign_id = cc.campaign_id;

COMMIT;
