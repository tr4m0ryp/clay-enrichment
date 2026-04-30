-- 016_leads_full_gemini_status.sql
-- Add a fourth state to prospeo_status -- 'gemini' -- for contacts
-- where Prospeo missed but Gemini's grounded fallback found the
-- LinkedIn URL or email. Order matters: 'found' is still Prospeo
-- (highest signal), then 'gemini', then 'not_found' (both providers
-- gave up), then 'pending' (resolver hasn't reached the contact).

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
    -- Enrichment status precedence:
    --   'found'     -- Prospeo returned a credit-spending match
    --   'gemini'    -- Prospeo missed; Gemini grounded fallback
    --                  surfaced a LinkedIn URL or email
    --   'not_found' -- Prospeo logged a NO_MATCH (or pre-logging
    --                  resolver touch) AND Gemini either ran with
    --                  no result, errored, or hasn't been tried
    --   'pending'   -- resolver hasn't reached this contact yet
    CASE
        WHEN EXISTS (
            SELECT 1 FROM prospeo_usage pu
            WHERE pu.contact_id = cc.contact_id
              AND pu.credits > 0
        ) THEN 'found'
        WHEN EXISTS (
            SELECT 1 FROM gemini_finder_usage gu
            WHERE gu.contact_id = cc.contact_id
              AND (gu.found_email OR gu.found_linkedin)
        ) THEN 'gemini'
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
