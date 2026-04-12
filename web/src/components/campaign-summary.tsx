import Link from "next/link";
import {
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { DataTable } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface CampaignRow {
  id: string;
  name: string;
  status: string;
  companies: number;
  leads: number;
  emails: number;
}

function statusVariant(status: string) {
  switch (status) {
    case "Active":
      return "brand" as const;
    case "Paused":
      return "default" as const;
    case "Completed":
      return "success" as const;
    case "Abort":
      return "destructive" as const;
    default:
      return "outline" as const;
  }
}

export function CampaignSummary({ rows }: { rows: CampaignRow[] }) {
  if (rows.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Campaign Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No campaigns yet.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div>
      <h2 className="mb-3 text-sm font-semibold text-foreground">
        Campaign Summary
      </h2>
      <DataTable count={rows.length} colSpan={5}>
        <TableHeader>
          <TableRow>
            <TableHead>Campaign</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Companies</TableHead>
            <TableHead className="text-right">Leads</TableHead>
            <TableHead className="text-right">Emails</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id}>
              <TableCell className="font-medium">
                <Link
                  href={`/campaigns/${row.id}`}
                  className="text-foreground hover:text-primary hover:underline underline-offset-4"
                >
                  {row.name}
                </Link>
              </TableCell>
              <TableCell>
                <Badge variant={statusVariant(row.status)}>
                  {row.status}
                </Badge>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {row.companies}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {row.leads}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {row.emails}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </DataTable>
    </div>
  );
}
