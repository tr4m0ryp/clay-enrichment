import { client, unwrap } from "./_client";

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

export async function getCampaigns() {
  const { data, error } = await client()
    .from("campaigns_with_counts")
    .select("*")
    .order("created_at", { ascending: false });
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function getCampaignById(id: string) {
  const { data, error } = await client()
    .from("campaigns")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

export async function getCampaignsList() {
  const { data, error } = await client()
    .from("campaigns")
    .select("id, name")
    .order("name");
  return unwrap<Array<{ id: string; name: string }>>(data, error);
}

export async function getCampaignStats(campaignId: string) {
  const c = client();
  const [companies, contacts, leads, emails] = await Promise.all([
    c
      .from("company_campaigns")
      .select("*", { count: "exact", head: true })
      .eq("campaign_id", campaignId),
    c
      .from("contact_campaign_links")
      .select("*", { count: "exact", head: true })
      .eq("campaign_id", campaignId),
    c
      .from("contact_campaigns")
      .select("*", { count: "exact", head: true })
      .eq("campaign_id", campaignId)
      .gte("relevance_score", 7),
    c
      .from("emails")
      .select("*", { count: "exact", head: true })
      .eq("campaign_id", campaignId),
  ]);
  for (const r of [companies, contacts, leads, emails]) {
    if (r.error) throw new Error(r.error.message);
  }
  return {
    companies: companies.count ?? 0,
    contacts: contacts.count ?? 0,
    highPriorityLeads: leads.count ?? 0,
    emails: emails.count ?? 0,
  };
}

export async function getCampaignEmailTimeline() {
  const { data, error } = await client()
    .from("campaign_email_timeline")
    .select("*")
    .order("day", { ascending: true });
  return unwrap<Record<string, unknown>[]>(data, error);
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export async function updateCampaignStatus(id: string, status: string) {
  const { error } = await client()
    .from("campaigns")
    .update({ status, updated_at: new Date().toISOString() })
    .eq("id", id);
  if (error) throw new Error(error.message);
}

export async function updateCampaignTargetDescription(
  id: string,
  description: string,
) {
  const { error } = await client()
    .from("campaigns")
    .update({
      target_description: description,
      updated_at: new Date().toISOString(),
    })
    .eq("id", id);
  if (error) throw new Error(error.message);
}

export async function insertCampaign(name: string, targetDescription: string) {
  const { error } = await client()
    .from("campaigns")
    .insert({ name, target_description: targetDescription });
  if (error) throw new Error(error.message);
}
