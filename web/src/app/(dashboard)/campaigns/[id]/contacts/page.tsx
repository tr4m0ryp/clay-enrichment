import Link from "next/link";
import { getContactsByCampaign } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DataTable } from "@/components/ui/data-table";

function statusVariant(
  status: string,
): "default" | "success" | "warning" | "outline" {
  switch (status) {
    case "Researched":
      return "success";
    case "Enriched":
      return "success";
    case "Email Generated":
      return "success";
    default:
      return "outline";
  }
}

export default async function CampaignContactsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const contacts = await getContactsByCampaign(id);

  return (
    <div>
      <h1 className="text-lg font-semibold text-foreground">Contacts</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Contacts linked to this campaign.
      </p>

      <div className="mt-6">
        <DataTable
          count={contacts.length}
          empty="No contacts linked to this campaign yet."
          colSpan={6}
        >
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Job Title</TableHead>
              <TableHead>Company</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Verified</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          {contacts.length > 0 && (
            <TableBody>
              {contacts.map((ct: Record<string, unknown>) => (
                <TableRow key={ct.id as string}>
                  <TableCell className="font-medium">
                    <Link
                      prefetch
                      href={`/contacts/${ct.id}`}
                      className="hover:text-primary hover:underline underline-offset-4"
                    >
                      {(ct.name as string) || "--"}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {(ct.job_title as string) || "--"}
                  </TableCell>
                  <TableCell>
                    {ct.company_id ? (
                      <Link
                        prefetch
                        href={`/companies/${ct.company_id}`}
                        className="text-primary hover:underline underline-offset-4"
                      >
                        {(ct.company_name as string) || "--"}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">--</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground font-mono text-xs">
                    {(ct.email as string) || "--"}
                  </TableCell>
                  <TableCell>
                    {ct.email_verified ? (
                      <Badge variant="success" dot>Verified</Badge>
                    ) : (
                      <Badge variant="outline" dot>No</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(ct.status as string)}>
                      {ct.status as string}
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
