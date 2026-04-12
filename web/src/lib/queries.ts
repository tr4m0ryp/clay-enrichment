import { sql } from "./db";

// ---------------------------------------------------------------------------
// Campaigns
// ---------------------------------------------------------------------------

export async function getCampaigns() {
  return sql`SELECT * FROM campaigns ORDER BY created_at DESC`;
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
      LIMIT 100
    `;
  }
  return sql`
    SELECT c.*, array_agg(DISTINCT camp.name) FILTER (WHERE camp.name IS NOT NULL) AS campaign_names
    FROM companies c
    LEFT JOIN company_campaigns cc ON c.id = cc.company_id
    LEFT JOIN campaigns camp ON cc.campaign_id = camp.id
    GROUP BY c.id
    ORDER BY c.updated_at DESC
    LIMIT 100
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
      LIMIT 100
    `;
  }
  return sql`
    SELECT ct.*, co.name AS company_name
    FROM contacts ct
    LEFT JOIN companies co ON ct.company_id = co.id
    ORDER BY ct.updated_at DESC
    LIMIT 100
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
// Stats (dashboard)
// ---------------------------------------------------------------------------

export async function getStats() {
  const [campaigns, companies, contacts, emails, leads] = await Promise.all([
    sql`SELECT count(*)::int AS count FROM campaigns`,
    sql`SELECT count(*)::int AS count FROM companies`,
    sql`SELECT count(*)::int AS count FROM contacts`,
    sql`SELECT count(*)::int AS count FROM emails`,
    sql`SELECT count(*)::int AS count FROM contact_campaigns`,
  ]);

  return {
    campaigns: campaigns[0].count,
    companies: companies[0].count,
    contacts: contacts[0].count,
    emails: emails[0].count,
    leads: leads[0].count,
  };
}
