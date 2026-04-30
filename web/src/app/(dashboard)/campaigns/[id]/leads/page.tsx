import { getLeadsByCampaign } from "@/lib/queries";
import { LeadRow } from "@/app/(dashboard)/leads/lead-table";
import { LeadsView } from "@/app/(dashboard)/leads/leads-view";

export default async function CampaignLeadsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const leads = (await getLeadsByCampaign(id)) as unknown as LeadRow[];

  return (
    <LeadsView
      leads={leads}
      empty="No high-priority leads found for this campaign."
    />
  );
}
