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

// Insert with the full brief fields written in one shot. Used by the
// /campaigns/new flow's Approve action -- keeps the icp_brief / voice
// profile / banned_phrases / sample subject + body persisted alongside
// the original name + target_description. Returns the new row's id so
// the caller can redirect to /campaigns/[id].
export interface InsertCampaignFullArgs {
  name: string;
  target_description: string;
  email_style_profile: string;
  sample_email_subject: string;
  sample_email_body: string;
  icp_brief: string;
  banned_phrases: string[];
}

export async function insertCampaignFull(
  args: InsertCampaignFullArgs,
): Promise<string> {
  const { data, error } = await client()
    .from("campaigns")
    .insert({
      name: args.name,
      target_description: args.target_description,
      email_style_profile: args.email_style_profile,
      sample_email_subject: args.sample_email_subject,
      sample_email_body: args.sample_email_body,
      icp_brief: args.icp_brief,
      banned_phrases: args.banned_phrases,
    })
    .select("id")
    .single();
  if (error) throw new Error(error.message);
  if (!data || typeof data.id !== "string") {
    throw new Error("insertCampaignFull returned no id");
  }
  return data.id;
}
