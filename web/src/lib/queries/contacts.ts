import { client, unwrap } from "./_client";

export async function getContacts(status?: string) {
  let q = client()
    .from("contacts_with_company")
    .select("*")
    .order("updated_at", { ascending: false });
  if (status) q = q.eq("status", status);
  const { data, error } = await q;
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function getContactById(id: string) {
  const { data, error } = await client()
    .from("contacts_with_company")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

export async function getContactsByCompany(companyId: string) {
  const { data, error } = await client()
    .from("contacts")
    .select("*")
    .eq("company_id", companyId)
    .order("updated_at", { ascending: false });
  return unwrap<Record<string, unknown>[]>(data, error);
}

export async function getContactsByCampaign(campaignId: string) {
  const { data, error } = await client()
    .from("contact_campaign_links")
    .select("contact_id, contacts:contacts!inner(*, company:companies(name))")
    .eq("campaign_id", campaignId);
  if (error) throw new Error(error.message);
  type Contact = Record<string, unknown> & {
    company?: { name: string | null } | { name: string | null }[] | null;
  };
  type Row = {
    contact_id: string;
    contacts: Contact | Contact[] | null;
  };
  const rows = (data ?? []) as unknown as Row[];
  const list: Record<string, unknown>[] = [];
  for (const row of rows) {
    if (!row.contacts) continue;
    const contacts = Array.isArray(row.contacts) ? row.contacts : [row.contacts];
    for (const c of contacts) {
      const company = Array.isArray(c.company) ? c.company[0] : c.company;
      const company_name = company?.name ?? null;
      const out = { ...c, company_name } as Record<string, unknown>;
      delete (out as { company?: unknown }).company;
      list.push(out);
    }
  }
  list.sort((a, b) => {
    const left = String(a.updated_at ?? "");
    const right = String(b.updated_at ?? "");
    return right.localeCompare(left);
  });
  return list;
}
