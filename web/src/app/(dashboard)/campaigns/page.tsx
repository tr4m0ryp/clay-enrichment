import Link from "next/link";
import { getCampaigns } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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

function truncate(text: string, max: number) {
  if (!text || text.length <= max) return text || "";
  return text.slice(0, max) + "...";
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
      </div>

      <div className="mt-6 rounded-lg border border-border">
        <Table>
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
          <TableBody>
            {campaigns.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-8 text-center text-muted-foreground"
                >
                  No campaigns yet.
                </TableCell>
              </TableRow>
            )}
            {campaigns.map((c: Record<string, unknown>) => (
              <TableRow
                key={c.id as string}
                className="hover:bg-muted/50 transition-colors"
              >
                <TableCell className="font-medium">
                  <Link
                    href={`/campaigns/${c.id}`}
                    className="text-foreground hover:text-primary underline-offset-4 hover:underline"
                  >
                    {c.name as string}
                  </Link>
                </TableCell>
                <TableCell>
                  <Badge variant={statusBadgeVariant(c.status as string)}>
                    {c.status as string}
                  </Badge>
                </TableCell>
                <TableCell className="max-w-[280px] text-muted-foreground">
                  {truncate(c.target_description as string, 80)}
                </TableCell>
                <TableCell className="text-right tabular-nums">--</TableCell>
                <TableCell className="text-right tabular-nums">--</TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(c.created_at as string)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
