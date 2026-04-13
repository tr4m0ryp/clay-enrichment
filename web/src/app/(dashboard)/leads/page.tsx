import { sql } from "@/lib/db";
import {
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DataTable } from "@/components/ui/data-table";
import { CampaignFilter } from "./campaign-filter";
import { LeadRow, LeadTableRow } from "./lead-table";

interface Campaign {
  id: string;
  name: string;
}

async function getHighPriorityLeads(campaignId?: string): Promise<LeadRow[]> {
  if (campaignId && campaignId !== "all") {
    return sql`
      SELECT
        cc.id, cc.name, cc.job_title, cc.company_name, cc.email,
        cc.linkedin_url, cc.company_fit_score, cc.relevance_score,
        cc.outreach_status, cc.email_subject, cc.campaign_id,
        cc.score_reasoning, cc.context, cc.personalized_context,
        c.name AS campaign_name,
        co.website AS company_url,
        e.body AS email_body
      FROM contact_campaigns cc
      LEFT JOIN campaigns c ON c.id = cc.campaign_id
      LEFT JOIN companies co ON co.id = cc.company_id
      LEFT JOIN emails e ON e.contact_id = cc.contact_id AND e.campaign_id = cc.campaign_id
      WHERE cc.campaign_id = ${campaignId}
        AND (cc.company_fit_score >= 7 OR cc.relevance_score >= 7)
      ORDER BY cc.relevance_score DESC NULLS LAST, cc.company_fit_score DESC NULLS LAST
    ` as unknown as LeadRow[];
  }
  return sql`
    SELECT
      cc.id, cc.name, cc.job_title, cc.company_name, cc.email,
      cc.linkedin_url, cc.company_fit_score, cc.relevance_score,
      cc.outreach_status, cc.email_subject, cc.campaign_id,
      cc.score_reasoning, cc.context, cc.personalized_context,
      c.name AS campaign_name,
      co.website AS company_url,
      e.body AS email_body
    FROM contact_campaigns cc
    LEFT JOIN campaigns c ON c.id = cc.campaign_id
    LEFT JOIN companies co ON co.id = cc.company_id
    LEFT JOIN emails e ON e.contact_id = cc.contact_id AND e.campaign_id = cc.campaign_id
    WHERE cc.company_fit_score >= 7 OR cc.relevance_score >= 7
    ORDER BY cc.relevance_score DESC NULLS LAST, cc.company_fit_score DESC NULLS LAST
  ` as unknown as LeadRow[];
}

async function getCampaigns(): Promise<Campaign[]> {
  return sql`SELECT id, name FROM campaigns ORDER BY name` as unknown as Campaign[];
}

export default async function LeadsPage({
  searchParams,
}: {
  searchParams: Promise<{ campaign?: string }>;
}) {
  const params = await searchParams;
  const campaignFilter = params.campaign ?? "all";
  const [leads, campaigns] = await Promise.all([
    getHighPriorityLeads(campaignFilter),
    getCampaigns(),
  ]);

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
        <CampaignFilter campaigns={campaigns} current={campaignFilter} />
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
            <TableHead>LinkedIn</TableHead>
            <TableHead className="text-right">Fit</TableHead>
            <TableHead className="text-right">Relevance</TableHead>
            <TableHead>Email Subject</TableHead>
            <TableHead>Email Content</TableHead>
            <TableHead>Outreach</TableHead>
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
