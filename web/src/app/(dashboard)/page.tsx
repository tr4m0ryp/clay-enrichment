import Link from "next/link";
import {
  getCampaigns,
  getDashboardStats,
  getCampaignEmailTimeline,
} from "@/lib/queries";
import { StatsCard } from "@/components/stats-card";
import { CampaignChart } from "@/components/campaign-chart";
import { Badge } from "@/components/ui/badge";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DataTable } from "@/components/ui/data-table";
import { CreateCampaignForm } from "./campaigns/create-campaign-form";

export const dynamic = "force-dynamic";

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

function formatDate(date: string | Date) {
  return new Date(date).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default async function DashboardPage() {
  const [stats, campaigns, timeline] = await Promise.all([
    getDashboardStats(),
    getCampaigns(),
    getCampaignEmailTimeline(),
  ]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Operations overview and campaigns.
          </p>
        </div>
        <CreateCampaignForm />
      </div>

      {/* Operational stats */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Emails Sent"
          value={stats.emailsSent}
          description="Successfully delivered"
          highlight
        />
        <StatsCard
          title="Emails Pending"
          value={stats.emailsPending}
          description="Awaiting review or send"
        />
        <StatsCard
          title="Emails Failed"
          value={stats.emailsFailed}
          description="Bounced or failed"
        />
        <StatsCard
          title="Active Campaigns"
          value={stats.activeCampaigns}
          description="Currently running"
          highlight
        />
      </div>

      {/* Campaign progress chart */}
      <div>
        <h2 className="mb-3 text-sm font-semibold text-foreground">
          Campaign Progress
        </h2>
        <div className="rounded-md border border-border p-4">
          <CampaignChart
            data={timeline as unknown as Array<{
              campaign_id: string;
              campaign_name: string;
              day: string;
              cumulative: number;
            }>}
          />
        </div>
      </div>

      {/* Campaigns table */}
      <div>
        <h2 className="mb-3 text-sm font-semibold text-foreground">
          Campaigns
        </h2>
        <DataTable
          count={campaigns.length}
          empty="No campaigns yet."
          colSpan={6}
        >
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Target Description</TableHead>
              <TableHead className="text-right">Companies</TableHead>
              <TableHead className="text-right">Contacts</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          {campaigns.length > 0 && (
            <TableBody>
              {campaigns.map((c: Record<string, unknown>) => (
                <TableRow key={c.id as string}>
                  <TableCell className="font-medium">
                    <Link
                      prefetch
                      href={`/campaigns/${c.id}`}
                      className="text-foreground hover:text-primary hover:underline underline-offset-4"
                    >
                      {c.name as string}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusBadgeVariant(c.status as string)}>
                      {c.status as string}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {(c.target_description as string)?.slice(0, 80) || "--"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {(c.company_count as number) ?? 0}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {(c.contact_count as number) ?? 0}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(c.created_at as string)}
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
