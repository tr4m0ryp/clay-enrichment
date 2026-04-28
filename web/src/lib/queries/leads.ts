import { client, unwrap } from "./_client";

// Reads against the leads_full view (defined in schema/006_views.sql).
// "Leads" = contact_campaigns rows enriched with campaign name, company
// URL, and the matching email body (when one has been generated).

export async function getContactCampaigns(campaignId?: string) {
  let q = client()
    .from("contact_campaigns")
    .select("*")
    .order("relevance_score", { ascending: false, nullsFirst: false })
    .order("created_at", { ascending: false });
  if (campaignId) q = q.eq("campaign_id", campaignId);
  const { data, error } = await q;
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function getContactCampaignById(id: string) {
  const { data, error } = await client()
    .from("contact_campaigns")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

export async function getLeadsByCampaign(campaignId: string) {
  const { data, error } = await client()
    .from("leads_full")
    .select("*")
    .eq("campaign_id", campaignId)
    .or("company_fit_score.gte.7,relevance_score.gte.7")
    .order("relevance_score", { ascending: false, nullsFirst: false })
    .order("company_fit_score", { ascending: false, nullsFirst: false });
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function getHighPriorityLeads(campaignId?: string) {
  let q = client()
    .from("leads_full")
    .select("*")
    .or("company_fit_score.gte.7,relevance_score.gte.7")
    .order("relevance_score", { ascending: false, nullsFirst: false })
    .order("company_fit_score", { ascending: false, nullsFirst: false });
  if (campaignId && campaignId !== "all") q = q.eq("campaign_id", campaignId);
  const { data, error } = await q;
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function updateContactCampaignOutreach(
  id: string,
  status: string,
) {
  const { error } = await client()
    .from("contact_campaigns")
    .update({ outreach_status: status })
    .eq("id", id);
  if (error) throw new Error(error.message);
}
