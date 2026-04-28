import { client, unwrap } from "./_client";

export async function getCompanies(status?: string) {
  let q = client()
    .from("companies_with_campaigns")
    .select("*")
    .order("updated_at", { ascending: false });
  if (status) q = q.eq("status", status);
  const { data, error } = await q;
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function getCompanyById(id: string) {
  const { data, error } = await client()
    .from("companies")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

export async function getCampaignsByCompany(companyId: string) {
  const { data, error } = await client()
    .from("company_campaigns")
    .select("campaigns(*)")
    .eq("company_id", companyId);
  if (error) throw new Error(error.message);
  const rows = (data ?? []) as unknown as Array<{
    campaigns: Record<string, unknown> | Record<string, unknown>[] | null;
  }>;
  return rows
    .flatMap((r) =>
      r.campaigns ? (Array.isArray(r.campaigns) ? r.campaigns : [r.campaigns]) : [],
    )
    .sort((a, b) => String(a.name ?? "").localeCompare(String(b.name ?? "")));
}

export async function getCompaniesByCampaign(campaignId: string) {
  const { data, error } = await client()
    .from("company_campaigns")
    .select("companies(*)")
    .eq("campaign_id", campaignId);
  if (error) throw new Error(error.message);
  const rows = (data ?? []) as unknown as Array<{
    companies: Record<string, unknown> | Record<string, unknown>[] | null;
  }>;
  const list = rows.flatMap((r) =>
    r.companies ? (Array.isArray(r.companies) ? r.companies : [r.companies]) : [],
  );
  list.sort((a, b) => {
    const left = String(a.updated_at ?? "");
    const right = String(b.updated_at ?? "");
    return right.localeCompare(left);
  });
  return list;
}
