import Link from "next/link";
import { getCampaigns } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DataTable } from "@/components/ui/data-table";
import { CreateCampaignForm } from "./create-campaign-form";

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

export default async function CampaignsPage() {
  const campaigns = await getCampaigns();

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Campaigns</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            All outreach campaigns.
          </p>
        </div>
        <CreateCampaignForm />
      </div>

      <div className="mt-6">
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
