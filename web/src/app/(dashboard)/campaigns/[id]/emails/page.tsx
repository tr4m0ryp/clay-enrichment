import Link from "next/link";
import { getEmailsByCampaignWithContacts } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmailActions } from "@/app/(dashboard)/emails/email-actions";
import { CampaignEmailFilterTabs } from "./filter-tabs";

type EmailStatus = "Pending Review" | "Approved" | "Sent" | "Rejected";

const STATUS_BADGE: Record<
  EmailStatus,
  "warning" | "success" | "brand" | "destructive"
> = {
  "Pending Review": "warning",
  Approved: "success",
  Sent: "brand",
  Rejected: "destructive",
};

interface EmailRow {
  id: string;
  subject: string;
  body: string;
  status: EmailStatus;
  contact_name: string | null;
  company_name: string | null;
  contact_email: string | null;
  contact_id: string | null;
  created_at: string;
}

export default async function CampaignEmailsPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ status?: string }>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const filter = sp.status ?? "Pending Review";
  const emails = (await getEmailsByCampaignWithContacts(
    id,
    filter,
  )) as unknown as EmailRow[];

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-foreground">Email Review</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Review and approve outreach emails for this campaign.
        </p>
      </div>

      <CampaignEmailFilterTabs campaignId={id} current={filter} />

      {emails.length === 0 ? (
        <p className="mt-8 text-center text-sm text-muted-foreground">
          No emails with status &ldquo;{filter}&rdquo;.
        </p>
      ) : (
        <div className="mt-4 grid gap-4 sm:grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
          {emails.map((email) => (
            <Link
              key={email.id}
              href={`/emails/${email.id}`}
              className="block"
            >
              <Card className="cursor-pointer transition-shadow hover:shadow-md">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <CardTitle className="truncate text-sm">
                        {email.contact_name ?? "Unknown Contact"}
                      </CardTitle>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {email.company_name ?? "No company"}
                        {email.contact_email
                          ? ` -- ${email.contact_email}`
                          : ""}
                      </p>
                    </div>
                    <Badge
                      variant={
                        STATUS_BADGE[email.status as EmailStatus] ?? "default"
                      }
                    >
                      {email.status}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <p className="mb-2 text-sm font-medium text-foreground">
                    {email.subject}
                  </p>
                  <p className="line-clamp-4 text-xs leading-relaxed text-muted-foreground">
                    {email.body}
                  </p>
                  {email.status === "Pending Review" && (
                    <EmailActions emailId={email.id} />
                  )}
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
