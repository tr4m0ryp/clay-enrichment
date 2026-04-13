import Link from "next/link";
import { getCompaniesByCampaign } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DataTable } from "@/components/ui/data-table";

function scoreColor(score: number | null): string {
  if (score === null || score === undefined) return "text-muted-foreground";
  if (score >= 7) return "text-emerald-600 font-semibold";
  if (score >= 4) return "text-foreground";
  return "text-red-600 font-semibold";
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

      <div className="mt-6">
        <DataTable
          count={companies.length}
          empty="No companies linked to this campaign yet."
          colSpan={6}
        >
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Website</TableHead>
              <TableHead>Industry</TableHead>
              <TableHead>Location</TableHead>
              <TableHead className="text-right">DPP Fit</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          {companies.length > 0 && (
            <TableBody>
              {companies.map((c: Record<string, unknown>) => (
                <TableRow key={c.id as string}>
                  <TableCell className="font-medium">
                    <Link
                      prefetch
                      href={`/companies/${c.id}`}
                      className="hover:text-primary hover:underline underline-offset-4"
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
                        className="text-primary hover:underline underline-offset-4"
                      >
                        {(c.website as string).replace(/^https?:\/\//, "")}
                      </a>
                    ) : (
                      <span className="text-muted-foreground">--</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {(c.industry as string) || "--"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {(c.location as string) || "--"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    <span className={scoreColor(c.dpp_fit_score as number)}>
                      {c.dpp_fit_score != null ? String(c.dpp_fit_score) : "--"}
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
          )}
        </DataTable>
      </div>
    </div>
  );
}
