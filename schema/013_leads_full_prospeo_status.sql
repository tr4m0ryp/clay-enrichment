-- 013_leads_full_prospeo_status.sql
-- Surface a per-contact Prospeo-check status on leads_full so the
-- /leads dashboard can show whether each contact was found by Prospeo,
-- not present in Prospeo's DB, or still queued for resolution.

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
    -- Prospeo check status per contact:
    --   'found'     -- prospeo_usage has a credit-spending row for this
    --                  contact (Prospeo returned an actual match)
    --   'not_found' -- email_resolver has touched this row (updated_at
    --                  diverges from created_at) but no Prospeo row was
    --                  written, meaning the call returned NO_MATCH
    --   'pending'   -- resolver hasn't picked it up yet
    CASE
        WHEN EXISTS (
            SELECT 1 FROM prospeo_usage pu
            WHERE pu.contact_id = cc.contact_id
        ) THEN 'found'
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
