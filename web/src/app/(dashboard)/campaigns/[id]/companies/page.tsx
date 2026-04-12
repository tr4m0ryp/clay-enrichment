import Link from "next/link";
import { getCompaniesByCampaign } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function scoreColor(score: number | null): string {
  if (score === null || score === undefined) return "";
  if (score >= 7) return "text-primary font-semibold";
  if (score >= 4) return "";
  return "text-destructive font-semibold";
}

function statusVariant(
  status: string,
): "default" | "success" | "warning" | "outline" {
  switch (status) {
    case "Enriched":
      return "success";
    case "Partially Enriched":
      return "warning";
    case "Contacts Found":
      return "success";
    default:
      return "outline";
  }
}

export default async function CampaignCompaniesPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const companies = await getCompaniesByCampaign(id);

  return (
    <div>
      <h1 className="text-lg font-semibold text-foreground">Companies</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Companies linked to this campaign.
      </p>

      <div className="mt-6 rounded-lg border border-border overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Website</TableHead>
              <TableHead>Industry</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>DPP Fit Score</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {companies.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="text-center text-muted-foreground py-8"
                >
                  No companies linked to this campaign yet.
                </TableCell>
              </TableRow>
            )}
            {companies.map((c: Record<string, unknown>) => (
              <TableRow key={c.id as string} className="group">
                <TableCell>
                  <Link
                    href={`/companies/${c.id}`}
                    className="font-medium hover:underline"
                  >
                    {(c.name as string) || "--"}
                  </Link>
                </TableCell>
                <TableCell>
                  {c.website ? (
                    <a
                      href={c.website as string}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary hover:underline text-sm"
                    >
                      {(c.website as string).replace(/^https?:\/\//, "")}
                    </a>
                  ) : (
                    <span className="text-muted-foreground">--</span>
                  )}
                </TableCell>
                <TableCell className="text-sm">
                  {(c.industry as string) || "--"}
                </TableCell>
                <TableCell className="text-sm">
                  {(c.location as string) || "--"}
                </TableCell>
                <TableCell>
                  <span className={scoreColor(c.dpp_fit_score as number)}>
                    {c.dpp_fit_score !== null && c.dpp_fit_score !== undefined
                      ? String(c.dpp_fit_score)
                      : "--"}
                  </span>
                </TableCell>
                <TableCell>
                  <Badge variant={statusVariant(c.status as string)}>
                    {c.status as string}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
