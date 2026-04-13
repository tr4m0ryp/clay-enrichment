import { sql } from "./db";

// ---------------------------------------------------------------------------
// Campaigns
// ---------------------------------------------------------------------------

export async function getCampaigns() {
  return sql`
    SELECT
      c.*,
      coalesce(cc_co.cnt, 0)::int AS company_count,
      coalesce(cc_ct.cnt, 0)::int AS contact_count
    FROM campaigns c
    LEFT JOIN (
      SELECT campaign_id, count(*) AS cnt
      FROM company_campaigns
      GROUP BY campaign_id
    ) cc_co ON cc_co.campaign_id = c.id
    LEFT JOIN (
      SELECT campaign_id, count(*) AS cnt
      FROM contact_campaign_links
      GROUP BY campaign_id
    ) cc_ct ON cc_ct.campaign_id = c.id
    ORDER BY c.created_at DESC
  `;
}

export async function getCampaignById(id: string) {
  const rows = await sql`SELECT * FROM campaigns WHERE id = ${id}`;
  return rows[0] ?? null;
}

// ---------------------------------------------------------------------------
// Companies
// ---------------------------------------------------------------------------

export async function getCompanies(status?: string) {
  if (status) {
    return sql`
      SELECT c.*, array_agg(DISTINCT camp.name) FILTER (WHERE camp.name IS NOT NULL) AS campaign_names
      FROM companies c
      LEFT JOIN company_campaigns cc ON c.id = cc.company_id
      LEFT JOIN campaigns camp ON cc.campaign_id = camp.id
      WHERE c.status = ${status}
      GROUP BY c.id
      ORDER BY c.updated_at DESC
    `;
  }
  return sql`
    SELECT c.*, array_agg(DISTINCT camp.name) FILTER (WHERE camp.name IS NOT NULL) AS campaign_names
    FROM companies c
    LEFT JOIN company_campaigns cc ON c.id = cc.company_id
    LEFT JOIN campaigns camp ON cc.campaign_id = camp.id
    GROUP BY c.id
    ORDER BY c.updated_at DESC
  `;
}

export async function getCompanyById(id: string) {
  const rows = await sql`SELECT * FROM companies WHERE id = ${id}`;
  return rows[0] ?? null;
}

export async function getCampaignsByCompany(companyId: string) {
  return sql`
    SELECT camp.* FROM campaigns camp
    JOIN company_campaigns cc ON camp.id = cc.campaign_id
    WHERE cc.company_id = ${companyId}
    ORDER BY camp.name
  `;
}

// ---------------------------------------------------------------------------
// Contacts
// ---------------------------------------------------------------------------

export async function getContacts(status?: string) {
  if (status) {
    return sql`
      SELECT ct.*, co.name AS company_name
      FROM contacts ct
      LEFT JOIN companies co ON ct.company_id = co.id
      WHERE ct.status = ${status}
      ORDER BY ct.updated_at DESC
    `;
  }
  return sql`
    SELECT ct.*, co.name AS company_name
    FROM contacts ct
    LEFT JOIN companies co ON ct.company_id = co.id
    ORDER BY ct.updated_at DESC
  `;
}

export async function getContactById(id: string) {
  const rows = await sql`
    SELECT ct.*, co.name AS company_name
    FROM contacts ct
    LEFT JOIN companies co ON ct.company_id = co.id
    WHERE ct.id = ${id}
  `;
  return rows[0] ?? null;
}

export async function getContactsByCompany(companyId: string) {
  return sql`SELECT * FROM contacts WHERE company_id = ${companyId} ORDER BY updated_at DESC`;
}

// ---------------------------------------------------------------------------
// Emails
// ---------------------------------------------------------------------------

export async function getEmails(status?: string) {
  if (status) {
    return sql`SELECT * FROM emails WHERE status = ${status} ORDER BY created_at DESC`;
  }
  return sql`SELECT * FROM emails ORDER BY created_at DESC`;
}

export async function getEmailById(id: string) {
  const rows = await sql`SELECT * FROM emails WHERE id = ${id}`;
  return rows[0] ?? null;
}

export async function getEmailsByCampaign(campaignId: string) {
  return sql`SELECT * FROM emails WHERE campaign_id = ${campaignId} ORDER BY created_at DESC`;
}

// ---------------------------------------------------------------------------
// Contact Campaigns (leads)
// ---------------------------------------------------------------------------

export async function getContactCampaigns(campaignId?: string) {
  if (campaignId) {
    return sql`
      SELECT * FROM contact_campaigns
      WHERE campaign_id = ${campaignId}
      ORDER BY relevance_score DESC NULLS LAST, created_at DESC
    `;
  }
  return sql`
    SELECT * FROM contact_campaigns
    ORDER BY relevance_score DESC NULLS LAST, created_at DESC
  `;
}

export async function getContactCampaignById(id: string) {
  const rows = await sql`SELECT * FROM contact_campaigns WHERE id = ${id}`;
  return rows[0] ?? null;
}

// ---------------------------------------------------------------------------
// Campaign-scoped queries
// ---------------------------------------------------------------------------

export async function getCompaniesByCampaign(campaignId: string) {
  return sql`
    SELECT c.*
    FROM companies c
    JOIN company_campaigns cc ON c.id = cc.company_id
    WHERE cc.campaign_id = ${campaignId}
    ORDER BY c.updated_at DESC
  `;
}

export async function getContactsByCampaign(campaignId: string) {
  return sql`
    SELECT ct.*, co.name AS company_name
    FROM contacts ct
    JOIN contact_campaign_links ccl ON ct.id = ccl.contact_id
    LEFT JOIN companies co ON ct.company_id = co.id
    WHERE ccl.campaign_id = ${campaignId}
    ORDER BY ct.updated_at DESC
  `;
}

export async function getEmailsByCampaignWithContacts(
  campaignId: string,
  status?: string,
) {
  if (status && status !== "all") {
    return sql`
      SELECT
        e.id, e.subject, e.body, e.status, e.created_at, e.contact_id,
        ct.name AS contact_name, ct.email AS contact_email,
        co.name AS company_name
      FROM emails e
      LEFT JOIN contacts ct ON ct.id = e.contact_id
      LEFT JOIN companies co ON co.id = ct.company_id
      WHERE e.campaign_id = ${campaignId} AND e.status = ${status}
      ORDER BY e.created_at DESC
    `;
  }
  return sql`
    SELECT
      e.id, e.subject, e.body, e.status, e.created_at, e.contact_id,
      ct.name AS contact_name, ct.email AS contact_email,
      co.name AS company_name
    FROM emails e
    LEFT JOIN contacts ct ON ct.id = e.contact_id
    LEFT JOIN companies co ON co.id = ct.company_id
    WHERE e.campaign_id = ${campaignId}
    ORDER BY e.created_at DESC
  `;
}

export async function getLeadsByCampaign(campaignId: string) {
  return sql`
    SELECT
      cc.id, cc.name, cc.job_title, cc.company_name, cc.email,
      cc.linkedin_url, cc.company_fit_score, cc.relevance_score,
      cc.outreach_status, cc.email_subject, cc.campaign_id,
      cc.score_reasoning, cc.context, cc.personalized_context,
      co.website AS company_url,
      e.body AS email_body
    FROM contact_campaigns cc
    LEFT JOIN companies co ON co.id = cc.company_id
    LEFT JOIN emails e ON e.contact_id = cc.contact_id AND e.campaign_id = cc.campaign_id
    WHERE cc.campaign_id = ${campaignId}
      AND (cc.company_fit_score >= 7 OR cc.relevance_score >= 7)
    ORDER BY cc.relevance_score DESC NULLS LAST, cc.company_fit_score DESC NULLS LAST
  `;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export async function getSettings() {
  return sql`SELECT key, value FROM settings ORDER BY key`;
}

export async function getSenderAccounts() {
  return sql`
    SELECT id, email, daily_limit, is_active, created_at
    FROM sender_accounts
    ORDER BY created_at
  `;
}

// ---------------------------------------------------------------------------
// Stats (dashboard)
// ---------------------------------------------------------------------------

export async function getDashboardStats() {
  const [leadsFound, leadsEnriched, emailsReady, activeCampaigns] =
    await Promise.all([
      sql`SELECT count(*)::int AS count FROM contacts`,
      sql`SELECT count(*)::int AS count FROM contacts WHERE status IN ('Enriched', 'Researched', 'Email Generated')`,
      sql`SELECT count(*)::int AS count FROM emails WHERE status = 'Pending Review'`,
      sql`SELECT count(*)::int AS count FROM campaigns WHERE status = 'Active'`,
    ]);

  return {
    leadsFound: leadsFound[0].count as number,
    leadsEnriched: leadsEnriched[0].count as number,
    emailsReady: emailsReady[0].count as number,
    activeCampaigns: activeCampaigns[0].count as number,
  };
}

export async function getCampaignEmailTimeline() {
  return sql`
    SELECT
      c.id AS campaign_id,
      c.name AS campaign_name,
      e.day,
      e.daily_count,
      sum(e.daily_count) OVER (
        PARTITION BY c.id ORDER BY e.day
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      )::int AS cumulative
    FROM campaigns c
    JOIN (
      SELECT
        campaign_id,
        date_trunc('day', created_at)::date AS day,
        count(*)::int AS daily_count
      FROM emails
      GROUP BY campaign_id, date_trunc('day', created_at)::date
    ) e ON e.campaign_id = c.id
    ORDER BY e.day
  `;
}
