import { notFound } from "next/navigation";
import Link from "next/link";
import { sql } from "@/lib/db";
import { getCampaignById } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusActions } from "./status-actions";
import { DescriptionEditor } from "./description-editor";

function statusBadgeVariant(status: string) {
  switch (status) {
    case "Active":
      return "brand";
    case "Paused":
      return "default";
    case "Completed":
      return "success";
    case "Abort":
      return "destructive";
    default:
      return "outline";
  }
}

async function getCampaignStats(campaignId: string) {
  const [companies, contacts, leads, emails] = await Promise.all([
    sql`
      SELECT count(*)::int AS count FROM company_campaigns
      WHERE campaign_id = ${campaignId}
    `,
    sql`
      SELECT count(*)::int AS count FROM contact_campaign_links
      WHERE campaign_id = ${campaignId}
    `,
    sql`
      SELECT count(*)::int AS count FROM contact_campaigns
      WHERE campaign_id = ${campaignId}
      AND relevance_score IS NOT NULL
      AND relevance_score >= 7
    `,
    sql`
      SELECT count(*)::int AS count FROM emails
      WHERE campaign_id = ${campaignId}
    `,
  ]);

  return {
    companies: companies[0].count,
    contacts: contacts[0].count,
    highPriorityLeads: leads[0].count,
    emails: emails[0].count,
  };
}

export default async function CampaignDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const campaign = await getCampaignById(id);
  if (!campaign) notFound();

  const stats = await getCampaignStats(id);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link
            href="/campaigns"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            Campaigns
          </Link>
          <h1 className="mt-1 text-2xl font-semibold text-foreground">
            {campaign.name}
          </h1>
          <div className="mt-2 flex items-center gap-3">
            <Badge variant={statusBadgeVariant(campaign.status)}>
              {campaign.status}
            </Badge>
            <span className="text-sm text-muted-foreground">
              Created{" "}
              {new Date(campaign.created_at).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </span>
          </div>
        </div>
        <StatusActions campaignId={id} currentStatus={campaign.status} />
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Companies" value={stats.companies} href={`/companies?campaign=${id}`} />
        <StatCard label="Contacts" value={stats.contacts} href={`/contacts?campaign=${id}`} />
        <StatCard label="High-Priority Leads" value={stats.highPriorityLeads} href={`/leads?campaign=${id}`} />
        <StatCard label="Emails" value={stats.emails} href={`/emails?campaign=${id}`} />
      </div>

      {/* Target description */}
      <Card>
        <CardHeader>
          <CardTitle>Target Description</CardTitle>
        </CardHeader>
        <CardContent>
          <DescriptionEditor
            campaignId={id}
            initialValue={campaign.target_description ?? ""}
          />
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({
  label,
  value,
  href,
}: {
  label: string;
  value: number;
  href: string;
}) {
  return (
    <Link href={href}>
      <Card className="hover:border-primary/30 transition-colors">
        <CardContent className="p-4">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        </CardContent>
      </Card>
    </Link>
  );
}
