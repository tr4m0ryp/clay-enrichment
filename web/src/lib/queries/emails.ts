import { client, unwrap } from "./_client";

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

export async function getEmails(status?: string) {
  let q = client()
    .from("emails")
    .select("*")
    .order("created_at", { ascending: false });
  if (status) q = q.eq("status", status);
  const { data, error } = await q;
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function getEmailById(id: string) {
  const { data, error } = await client()
    .from("emails")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

export async function getEmailsByCampaign(campaignId: string) {
  const { data, error } = await client()
    .from("emails")
    .select("*")
    .eq("campaign_id", campaignId)
    .order("created_at", { ascending: false });
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function getEmailDetail(id: string) {
  const { data, error } = await client()
    .from("emails_with_contacts")
    .select(
      "id, subject, body, status, created_at, contact_id, contact_name, contact_email, contact_job_title, company_name, company_website",
    )
    .eq("id", id)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

export async function getEmailsWithContacts(status?: string) {
  let q = client()
    .from("emails_with_contacts")
    .select(
      "id, subject, body, status, created_at, contact_id, contact_name, contact_email, company_name",
    )
    .order("created_at", { ascending: false });
  if (status && status !== "all") q = q.eq("status", status);
  const { data, error } = await q;
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function getEmailsByCampaignWithContacts(
  campaignId: string,
  status?: string,
) {
  let q = client()
    .from("emails_with_contacts")
    .select(
      "id, subject, body, status, created_at, contact_id, contact_name, contact_email, company_name",
    )
    .eq("campaign_id", campaignId)
    .order("created_at", { ascending: false });
  if (status && status !== "all") q = q.eq("status", status);
  const { data, error } = await q;
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function getNextPendingEmailId(): Promise<string | null> {
  const { data, error } = await client()
    .from("emails")
    .select("id")
    .eq("status", "Pending Review")
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return (data?.id as string) ?? null;
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export async function approveEmailById(id: string) {
  const { error } = await client()
    .from("emails")
    .update({ status: "Approved" })
    .eq("id", id)
    .eq("status", "Pending Review");
  if (error) throw new Error(error.message);
}

export async function rejectEmailById(id: string) {
  const { error } = await client()
    .from("emails")
    .update({ status: "Rejected" })
    .eq("id", id)
    .eq("status", "Pending Review");
  if (error) throw new Error(error.message);
}

export async function updateEmailContent(
  id: string,
  subject: string,
  body: string,
) {
  const { error } = await client()
    .from("emails")
    .update({
      subject,
      body,
      status: "Pending Review",
      updated_at: new Date().toISOString(),
    })
    .eq("id", id);
  if (error) throw new Error(error.message);
}
