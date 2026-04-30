import { notFound } from "next/navigation";
import { getCompanyById, getCampaignsByCompany, getContactsByCompany } from "@/lib/queries";
import { CompanyDetail } from "@/components/company-detail";

export default async function CompanyDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ from?: string }>;
}) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const [company, campaigns, contacts] = await Promise.all([
    getCompanyById(id),
    getCampaignsByCompany(id),
    getContactsByCompany(id),
  ]);
  if (!company) notFound();
  const fromLeads = sp.from === "leads";
  return (
    <CompanyDetail
      company={company}
      campaigns={campaigns}
      contacts={contacts}
      backUrl={fromLeads ? "/leads" : "/companies"}
      backLabel={fromLeads ? "High-Priority Leads" : "Companies"}
    />
  );
}
