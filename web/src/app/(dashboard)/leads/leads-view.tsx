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

interface LeadsViewProps {
  leads: LeadRow[];
  empty?: string;
  // When provided, render the campaign filter dropdown.
  campaigns?: { id: string; name: string }[];
  campaignFilter?: string;
}

export function LeadsView({
  leads,
  empty = "No high-priority leads found.",
  campaigns,
  campaignFilter,
}: LeadsViewProps) {
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
          {campaigns && (
            <CampaignFilter
              campaigns={campaigns}
              current={campaignFilter ?? "all"}
            />
          )}
          <CsvExportButton leads={leads} />
        </div>
      </div>

      <DataTable count={leads.length} empty={empty} colSpan={14}>
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
