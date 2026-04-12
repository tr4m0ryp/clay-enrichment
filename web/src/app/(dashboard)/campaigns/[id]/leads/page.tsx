import { getLeadsByCampaign } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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

function scoreColor(score: number | null): "success" | "warning" | "default" {
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
  const leads = (await getLeadsByCampaign(id)) as LeadRow[];

  return (
    <div>
      <h1 className="text-lg font-semibold text-foreground">
        High-Priority Leads
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Contacts with a Fit or Relevance score of 7+.
      </p>

      {leads.length === 0 ? (
        <p className="mt-8 text-center text-sm text-muted-foreground">
          No high-priority leads found for this campaign.
        </p>
      ) : (
        <div className="mt-6 overflow-x-auto rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Company</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Job Title</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>LinkedIn</TableHead>
                <TableHead>Fit</TableHead>
                <TableHead>Relevance</TableHead>
                <TableHead>Outreach Status</TableHead>
                <TableHead>Email Subject</TableHead>
              </TableRow>
            </TableHeader>
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
                  <TableCell>
                    {lead.email ? (
                      <a
                        href={`mailto:${lead.email}`}
                        className="text-sm underline underline-offset-2"
                      >
                        {lead.email}
                      </a>
                    ) : (
                      "--"
                    )}
                  </TableCell>
                  <TableCell>
                    {lead.linkedin_url ? (
                      <a
                        href={lead.linkedin_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm underline underline-offset-2"
                      >
                        Profile
                      </a>
                    ) : (
                      "--"
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={scoreColor(lead.company_fit_score)}>
                      {lead.company_fit_score ?? "--"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={scoreColor(lead.relevance_score)}>
                      {lead.relevance_score ?? "--"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <OutreachSelect
                      leadId={lead.id}
                      current={lead.outreach_status}
                    />
                  </TableCell>
                  <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground">
                    {lead.email_subject ?? "--"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
