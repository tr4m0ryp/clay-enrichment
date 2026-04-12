import { getLeadsByCampaign } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DataTable } from "@/components/ui/data-table";
import { OutreachSelect } from "@/app/(dashboard)/leads/outreach-select";

interface LeadRow {
  id: string;
  name: string;
  job_title: string | null;
  company_name: string | null;
  email: string | null;
  linkedin_url: string | null;
  company_fit_score: number | null;
  relevance_score: number | null;
  outreach_status: string;
  email_subject: string | null;
}

function scoreVariant(score: number | null): "success" | "warning" | "default" {
  if (score == null) return "default";
  if (score >= 8) return "success";
  if (score >= 7) return "warning";
  return "default";
}

export default async function CampaignLeadsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const leads = (await getLeadsByCampaign(id)) as unknown as LeadRow[];

  return (
    <div>
      <h1 className="text-lg font-semibold text-foreground">
        High-Priority Leads
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Contacts with a Fit or Relevance score of 7+.
      </p>

      <div className="mt-6">
        <DataTable
          count={leads.length}
          empty="No high-priority leads found for this campaign."
          colSpan={9}
        >
          <TableHeader>
            <TableRow>
              <TableHead>Company</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Job Title</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>LinkedIn</TableHead>
              <TableHead className="text-right">Fit</TableHead>
              <TableHead className="text-right">Relevance</TableHead>
              <TableHead>Outreach</TableHead>
              <TableHead>Email Subject</TableHead>
            </TableRow>
          </TableHeader>
          {leads.length > 0 && (
            <TableBody>
              {leads.map((lead) => (
                <TableRow key={lead.id}>
                  <TableCell className="font-medium">
                    {lead.company_name ?? "--"}
                  </TableCell>
                  <TableCell>{lead.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {lead.job_title ?? "--"}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {lead.email ? (
                      <a
                        href={`mailto:${lead.email}`}
                        className="text-primary hover:underline underline-offset-4"
                      >
                        {lead.email}
                      </a>
                    ) : (
                      <span className="text-muted-foreground">--</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {lead.linkedin_url ? (
                      <a
                        href={lead.linkedin_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline underline-offset-4"
                      >
                        Profile
                      </a>
                    ) : (
                      <span className="text-muted-foreground">--</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <Badge variant={scoreVariant(lead.company_fit_score)} dot={false}>
                      {lead.company_fit_score ?? "--"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Badge variant={scoreVariant(lead.relevance_score)} dot={false}>
                      {lead.relevance_score ?? "--"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <OutreachSelect
                      leadId={lead.id}
                      current={lead.outreach_status}
                    />
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {lead.email_subject ?? "--"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          )}
        </DataTable>
      </div>
    </div>
  );
}
