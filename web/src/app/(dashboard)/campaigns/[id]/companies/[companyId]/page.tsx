import { notFound } from "next/navigation";
import { getCompanyById, getCampaignsByCompany, getContactsByCompany } from "@/lib/queries";
import { CompanyDetail } from "@/components/company-detail";

export default async function CampaignCompanyPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; companyId: string }>;
  searchParams: Promise<{ from?: string }>;
}) {
  const [{ id, companyId }, sp] = await Promise.all([params, searchParams]);
  const [company, campaigns, contacts] = await Promise.all([
    getCompanyById(companyId),
    getCampaignsByCompany(companyId),
    getContactsByCompany(companyId),
  ]);
  if (!company) notFound();
  const fromLeads = sp.from === "leads";
  return (
    <CompanyDetail
      company={company}
      campaigns={campaigns}
      contacts={contacts}
      backUrl={fromLeads ? `/campaigns/${id}/leads` : `/campaigns/${id}/companies`}
      backLabel={fromLeads ? "High-Priority Leads" : "Companies"}
      campaignId={id}
    />
  );
}
