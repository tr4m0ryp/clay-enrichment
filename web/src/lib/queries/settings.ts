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

// Total Prospeo monthly quota. Read from PROSPEO_MONTHLY_QUOTA env
// (set in web/.env.local on the server) so the cap is a single
// authoritative number rather than reconstructed from a key list
// the web process can't always see. Falls back to 1500 (the current
// 15-key × 100-credit pool size) if the env var is unset.
function getProspeoMonthlyQuota(): number {
  const raw = Number(process.env.PROSPEO_MONTHLY_QUOTA ?? 1500);
  return Number.isFinite(raw) && raw > 0 ? raw : 1500;
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
  const [validatedKeys, prospeoCalls, emailsReady, activeCampaigns] =
    await Promise.all([
      // Count harvested Gemini keys currently usable by the pool.
      // Same filter pick_validated_key uses at hand-out time so the
      // dashboard reflects what the runtime actually sees.
      c
        .from("validated_keys")
        .select("*", { count: "exact", head: true })
        .eq("status", "valid")
        .lt("consecutive_failures", 3),
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
  for (const r of [validatedKeys, emailsReady, activeCampaigns]) {
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
    validatedKeys: validatedKeys.count ?? 0,
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
