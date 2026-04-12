import Link from "next/link";
import { getContactsByCampaign } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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

      <div className="mt-6 rounded-lg border border-border overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Job Title</TableHead>
              <TableHead>Company</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Email Verified</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {contacts.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="text-center text-muted-foreground py-8"
                >
                  No contacts linked to this campaign yet.
                </TableCell>
              </TableRow>
            )}
            {contacts.map((ct: Record<string, unknown>) => (
              <TableRow key={ct.id as string}>
                <TableCell>
                  <Link
                    href={`/contacts/${ct.id}`}
                    className="font-medium hover:underline"
                  >
                    {(ct.name as string) || "--"}
                  </Link>
                </TableCell>
                <TableCell className="text-sm">
                  {(ct.job_title as string) || "--"}
                </TableCell>
                <TableCell>
                  {ct.company_id ? (
                    <Link
                      href={`/companies/${ct.company_id}`}
                      className="text-sm text-primary hover:underline"
                    >
                      {(ct.company_name as string) || "--"}
                    </Link>
                  ) : (
                    <span className="text-sm text-muted-foreground">--</span>
                  )}
                </TableCell>
                <TableCell className="text-sm">
                  {(ct.email as string) || "--"}
                </TableCell>
                <TableCell className="text-sm text-center">
                  {ct.email_verified ? "Yes" : "No"}
                </TableCell>
                <TableCell>
                  <Badge variant={statusVariant(ct.status as string)}>
                    {ct.status as string}
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
