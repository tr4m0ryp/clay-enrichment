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

// Total Prospeo monthly quota = (key count) * (per-key allowance).
// Set via env so 100/key/month can be tweaked without a redeploy
// when Prospeo's tier changes. Falls back to 1500 (15 keys * 100)
// which matches the current pool size.
const PROSPEO_MONTHLY_QUOTA = Number(
  process.env.PROSPEO_MONTHLY_QUOTA ?? 1500,
);

export async function getDashboardStats() {
  const c = client();
  // First-of-month UTC for the range filter. Indexed on used_at, so
  // the >= comparison hits the b-tree directly. Avoids to_char-based
  // generated columns (Postgres rejects them as non-IMMUTABLE).
  const now = new Date();
  const startOfMonth = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1),
  ).toISOString();
  const [leadsFound, prospeoUsed, emailsReady, activeCampaigns] =
    await Promise.all([
      c.from("contacts").select("*", { count: "exact", head: true }),
      c
        .from("prospeo_usage")
        .select("credits")
        .gte("used_at", startOfMonth),
      c
        .from("emails")
        .select("*", { count: "exact", head: true })
        .eq("status", "Pending Review"),
      c
        .from("campaigns")
        .select("*", { count: "exact", head: true })
        .eq("status", "Active"),
    ]);
  for (const r of [leadsFound, emailsReady, activeCampaigns]) {
    if (r.error) throw new Error(r.error.message);
  }
  if (prospeoUsed.error) {
    // Don't fail the whole dashboard if the usage table is unavailable
    // (e.g. schema migration not yet applied) -- just show 0/quota.
    console.warn("getDashboardStats: prospeo_usage read failed:", prospeoUsed.error.message);
  }
  const usedCredits = (prospeoUsed.data ?? []).reduce(
    (sum: number, row: { credits: number }) => sum + (row.credits ?? 0),
    0,
  );
  return {
    leadsFound: leadsFound.count ?? 0,
    prospeoUsed: usedCredits,
    prospeoTotal: PROSPEO_MONTHLY_QUOTA,
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
