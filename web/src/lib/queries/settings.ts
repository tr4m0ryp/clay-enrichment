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

// Total Prospeo monthly quota is derived: (configured key count) ×
// (per-key allowance). The key count is parsed from the same
// PROSPEO_API_KEYS env var the pipeline reads, so adding/removing
// keys auto-updates the dashboard total without a code change.
// Per-key allowance defaults to 100 (Prospeo free tier) and can be
// overridden via PROSPEO_QUOTA_PER_KEY.
function getProspeoMonthlyQuota(): number {
  const perKey = Number(process.env.PROSPEO_QUOTA_PER_KEY ?? 100);
  const raw = (process.env.PROSPEO_API_KEYS ?? "").trim();
  const keyCount = raw === ""
    ? 0
    : raw.split(",").map((s) => s.trim()).filter(Boolean).length;
  return Math.max(0, keyCount * perKey);
}

export async function getDashboardStats() {
  const c = client();
  // Rolling 30-day window (instead of calendar month). With 15 Prospeo
  // accounts each on its own per-account 30-day refresh cycle, no
  // single calendar-month reset matches reality -- a rolling window
  // approximates the aggregate behavior closely.
  const windowStart = new Date(
    Date.now() - 30 * 24 * 60 * 60 * 1000,
  ).toISOString();
  const [leadsFound, prospeoCalls, emailsReady, activeCampaigns] =
    await Promise.all([
      c.from("contacts").select("*", { count: "exact", head: true }),
      // Pull credits per row so we can derive both the call count
      // (=row count, includes free NO_MATCH calls) and the credit
      // total (=sum of credits, the actual budget figure).
      c
        .from("prospeo_usage")
        .select("credits")
        .gte("used_at", windowStart),
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
  if (prospeoCalls.error) {
    console.warn(
      "getDashboardStats: prospeo_usage read failed:",
      prospeoCalls.error.message,
    );
  }
  const rows = prospeoCalls.data ?? [];
  const callsCount = rows.length;
  const creditsUsed = rows.reduce(
    (sum: number, row: { credits: number }) => sum + (row.credits ?? 0),
    0,
  );
  return {
    leadsFound: leadsFound.count ?? 0,
    prospeoCalls: callsCount,
    prospeoCredits: creditsUsed,
    prospeoTotal: getProspeoMonthlyQuota(),
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
