import { getHighPriorityLeads, getCampaignsList } from "@/lib/queries";
import { LeadRow } from "./lead-table";
import { LeadsView } from "./leads-view";

export default async function LeadsPage({
  searchParams,
}: {
  searchParams: Promise<{ campaign?: string }>;
}) {
  const params = await searchParams;
  const campaignFilter = params.campaign ?? "all";
  const [leadsRaw, campaigns] = await Promise.all([
    getHighPriorityLeads(campaignFilter),
    getCampaignsList(),
  ]);
  const leads = leadsRaw as unknown as LeadRow[];

  return (
    <LeadsView
      leads={leads}
      campaigns={campaigns}
      campaignFilter={campaignFilter}
    />
  );
}
