import { sql } from "@/lib/db";
import { StatsCard } from "@/components/stats-card";
import { CampaignSummary } from "@/components/campaign-summary";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

export const dynamic = "force-dynamic";

async function getDashboardData() {
  const [
    companiesCount,
    contactsCount,
    highPriorityLeads,
    emailsSent,
    campaignRows,
    recentCompanies,
  ] = await Promise.all([
    sql`SELECT count(*)::int AS count FROM companies`,
    sql`SELECT count(*)::int AS count FROM contacts`,
    sql`
      SELECT count(*)::int AS count
      FROM contact_campaigns
      WHERE relevance_score >= 7
    `,
    sql`
      SELECT count(*)::int AS count
      FROM emails
      WHERE status = 'Sent'
    `,
    sql`
      SELECT
        c.id,
        c.name,
        c.status,
        coalesce(cc_co.cnt, 0)::int AS companies,
        coalesce(cc_l.cnt, 0)::int  AS leads,
        coalesce(e.cnt, 0)::int     AS emails
      FROM campaigns c
      LEFT JOIN (
        SELECT campaign_id, count(*) AS cnt
        FROM company_campaigns
        GROUP BY campaign_id
      ) cc_co ON cc_co.campaign_id = c.id
      LEFT JOIN (
        SELECT campaign_id, count(*) AS cnt
        FROM contact_campaigns
        GROUP BY campaign_id
      ) cc_l ON cc_l.campaign_id = c.id
      LEFT JOIN (
        SELECT campaign_id, count(*) AS cnt
        FROM emails
        GROUP BY campaign_id
      ) e ON e.campaign_id = c.id
      ORDER BY c.created_at DESC
    `,
    sql`
      SELECT id, name, status, industry, updated_at
      FROM companies
      ORDER BY updated_at DESC
      LIMIT 10
    `,
  ]);

  return {
    companies: companiesCount[0].count as number,
    contacts: contactsCount[0].count as number,
    highPriorityLeads: highPriorityLeads[0].count as number,
    emailsSent: emailsSent[0].count as number,
    campaignRows: campaignRows as unknown as Array<{
      id: string;
      name: string;
      status: string;
      companies: number;
      leads: number;
      emails: number;
    }>,
    recentCompanies: recentCompanies as unknown as Array<{
      id: string;
      name: string;
      status: string;
      industry: string | null;
      updated_at: Date;
    }>,
  };
}

function companyStatusVariant(status: string) {
  switch (status) {
    case "Enriched":
      return "success" as const;
    case "Partially Enriched":
      return "warning" as const;
    case "Contacts Found":
      return "brand" as const;
    default:
      return "outline" as const;
  }
}

export default async function DashboardPage() {
  const data = await getDashboardData();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Dashboard</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Pipeline overview and key metrics.
        </p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Companies"
          value={data.companies}
          description="Total discovered companies"
        />
        <StatsCard
          title="Contacts"
          value={data.contacts}
          description="Total contacts found"
        />
        <StatsCard
          title="High-Priority Leads"
          value={data.highPriorityLeads}
          description="Relevance score >= 7"
          highlight
        />
        <StatsCard
          title="Emails Sent"
          value={data.emailsSent}
          description="Successfully delivered"
          highlight
        />
      </div>

      {/* Campaign summary */}
      <CampaignSummary rows={data.campaignRows} />

      {/* Recent activity */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Activity</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {data.recentCompanies.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-muted-foreground">
              No companies yet.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Company</TableHead>
                  <TableHead>Industry</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.recentCompanies.map((company) => (
                  <TableRow key={company.id}>
                    <TableCell className="font-medium">
                      {company.name}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {company.industry ?? "--"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={companyStatusVariant(company.status)}>
                        {company.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground tabular-nums">
                      {new Date(company.updated_at).toLocaleDateString(
                        "en-US",
                        {
                          month: "short",
                          day: "numeric",
                        },
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
