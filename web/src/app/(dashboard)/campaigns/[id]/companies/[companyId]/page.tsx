import { notFound } from "next/navigation";
import { getCompanyById, getCampaignsByCompany, getContactsByCompany } from "@/lib/queries";
import { CompanyDetail } from "@/components/company-detail";

export default async function CampaignCompanyPage({
  params,
}: {
  params: Promise<{ id: string; companyId: string }>;
}) {
  const { id, companyId } = await params;
  const [company, campaigns, contacts] = await Promise.all([
    getCompanyById(companyId),
    getCampaignsByCompany(companyId),
    getContactsByCompany(companyId),
  ]);
  if (!company) notFound();
  return (
    <CompanyDetail
      company={company}
      campaigns={campaigns}
      contacts={contacts}
      backUrl={`/campaigns/${id}/companies`}
      campaignId={id}
    />
  );
}
