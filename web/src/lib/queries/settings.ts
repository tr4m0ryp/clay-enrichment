import { client, unwrap } from "./_client";

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

export async function getSettings() {
  const { data, error } = await client()
    .from("settings")
    .select("key, value")
    .order("key");
  return unwrap<Array<{ key: string; value: string }>>(data, error);
}

export async function getSenderAccounts() {
  const { data, error } = await client()
    .from("sender_accounts")
    .select("id, email, daily_limit, is_active, created_at")
    .order("created_at");
  return unwrap<
    Array<{
      id: string;
      email: string;
      daily_limit: number;
      is_active: boolean;
      created_at: string;
    }>
  >(data, error);
}

export async function getDashboardStats() {
  const c = client();
  const [leadsFound, leadsEnriched, emailsReady, activeCampaigns] =
    await Promise.all([
      c.from("contacts").select("*", { count: "exact", head: true }),
      c
        .from("contacts")
        .select("*", { count: "exact", head: true })
        .in("status", ["Enriched", "Researched", "Email Generated"]),
      c
        .from("emails")
        .select("*", { count: "exact", head: true })
        .eq("status", "Pending Review"),
      c
        .from("campaigns")
        .select("*", { count: "exact", head: true })
        .eq("status", "Active"),
    ]);
  for (const r of [leadsFound, leadsEnriched, emailsReady, activeCampaigns]) {
    if (r.error) throw new Error(r.error.message);
  }
  return {
    leadsFound: leadsFound.count ?? 0,
    leadsEnriched: leadsEnriched.count ?? 0,
    emailsReady: emailsReady.count ?? 0,
    activeCampaigns: activeCampaigns.count ?? 0,
  };
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export async function upsertSetting(key: string, value: string) {
  const { error } = await client()
    .from("settings")
    .upsert({ key, value, updated_at: new Date().toISOString() });
  if (error) throw new Error(error.message);
}

export async function deleteSetting(key: string) {
  const { error } = await client().from("settings").delete().eq("key", key);
  if (error) throw new Error(error.message);
}

export async function insertSenderAccount(
  email: string,
  password: string,
  dailyLimit: number,
) {
  const { error } = await client()
    .from("sender_accounts")
    .insert({ email, password, daily_limit: dailyLimit });
  if (error) throw new Error(error.message);
}

export async function deleteSenderAccount(id: string) {
  const { error } = await client()
    .from("sender_accounts")
    .delete()
    .eq("id", id);
  if (error) throw new Error(error.message);
}

export async function setSenderAccountActive(id: string, isActive: boolean) {
  const { error } = await client()
    .from("sender_accounts")
    .update({ is_active: isActive })
    .eq("id", id);
  if (error) throw new Error(error.message);
}
