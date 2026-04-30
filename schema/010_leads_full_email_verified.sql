-- 010_leads_full_email_verified.sql
-- Surface contact_campaigns.email_verified through the leads_full view so the
-- /leads dashboard can show a verified badge next to the contact email.

BEGIN;

-- DROP first because Postgres rejects column-order changes on a
-- CREATE OR REPLACE VIEW (cannot insert email_verified between two
-- existing columns).
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
