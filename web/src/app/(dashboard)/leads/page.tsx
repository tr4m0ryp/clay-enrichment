import {
  getHighPriorityLeads,
  getCampaignsList,
} from "@/lib/queries";
import {
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DataTable } from "@/components/ui/data-table";
import { CampaignFilter } from "./campaign-filter";
import { CsvExportButton } from "./csv-export-button";
import { LeadRow, LeadTableRow } from "./lead-table";

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
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold text-foreground">
            High-Priority Leads
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Contacts with a Fit or Relevance score of 7+.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <CampaignFilter campaigns={campaigns} current={campaignFilter} />
          <CsvExportButton leads={leads} />
        </div>
      </div>

      <DataTable
        count={leads.length}
        empty="No high-priority leads found."
        colSpan={14}
      >
        <TableHeader>
          <TableRow>
            <TableHead>Company</TableHead>
            <TableHead>Company URL</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Job Title</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Verified</TableHead>
            <TableHead>LinkedIn</TableHead>
            <TableHead className="text-right">Fit</TableHead>
            <TableHead className="text-right">Relevance</TableHead>
            <TableHead>Email Subject</TableHead>
            <TableHead>Email Content</TableHead>
            <TableHead>Score Reasoning</TableHead>
            <TableHead>Context</TableHead>
            <TableHead>Personalized Context</TableHead>
          </TableRow>
        </TableHeader>
        {leads.length > 0 && (
          <TableBody>
            {leads.map((lead) => (
              <LeadTableRow key={lead.id} lead={lead} />
            ))}
          </TableBody>
        )}
      </DataTable>
    </div>
  );
}
