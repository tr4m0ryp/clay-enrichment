import Link from "next/link";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
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
      return "success" as const;
    case "Paused":
      return "warning" as const;
    case "Completed":
      return "default" as const;
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
    <Card>
      <CardHeader>
        <CardTitle>Campaign Summary</CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-0">
        <Table>
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
                    className="text-foreground hover:text-primary underline-offset-4 hover:underline"
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
        </Table>
      </CardContent>
    </Card>
  );
}
