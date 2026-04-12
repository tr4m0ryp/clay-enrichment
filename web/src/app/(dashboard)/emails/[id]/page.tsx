import { notFound } from "next/navigation";
import Link from "next/link";
import { sql } from "@/lib/db";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmailActions } from "../email-actions";
import { EmailEditor } from "./email-editor";

type EmailStatus = "Pending Review" | "Approved" | "Sent" | "Rejected";

const STATUS_BADGE: Record<EmailStatus, "warning" | "success" | "brand" | "destructive"> = {
  "Pending Review": "warning",
  Approved: "success",
  Sent: "brand",
  Rejected: "destructive",
};

interface EmailDetail {
  id: string;
  subject: string;
  body: string;
  status: EmailStatus;
  created_at: string;
  contact_id: string | null;
  contact_name: string | null;
  contact_email: string | null;
  contact_job_title: string | null;
  company_name: string | null;
  company_website: string | null;
}

async function getEmailDetail(id: string): Promise<EmailDetail | null> {
  const rows = await sql`
    SELECT
      e.id,
      e.subject,
      e.body,
      e.status,
      e.created_at,
      e.contact_id,
      ct.name       AS contact_name,
      ct.email      AS contact_email,
      ct.job_title  AS contact_job_title,
      co.name       AS company_name,
      co.website    AS company_website
    FROM emails e
    LEFT JOIN contacts ct ON ct.id = e.contact_id
    LEFT JOIN companies co ON co.id = ct.company_id
    WHERE e.id = ${id}
  `;
  return (rows[0] as EmailDetail) ?? null;
}

export default async function EmailDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const email = await getEmailDetail(id);

  if (!email) notFound();

  const date = new Date(email.created_at).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="space-y-6">
      <Link
        href="/emails"
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        &larr; Email Review
      </Link>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">
            {email.contact_name ?? "Unknown Contact"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">{date}</p>
        </div>
        <Badge
          variant={STATUS_BADGE[email.status] ?? "default"}
          className="shrink-0"
        >
          {email.status}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recipient</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3">
            <div>
              <dt className="text-xs text-muted-foreground">Name</dt>
              <dd className="mt-0.5 text-sm">
                {email.contact_id ? (
                  <Link
                    href={`/contacts/${email.contact_id}`}
                    className="text-primary hover:underline"
                  >
                    {email.contact_name ?? "Unknown"}
                  </Link>
                ) : (
                  email.contact_name ?? "Unknown"
                )}
              </dd>
            </div>
            {email.contact_job_title && (
              <div>
                <dt className="text-xs text-muted-foreground">Title</dt>
                <dd className="mt-0.5 text-sm">{email.contact_job_title}</dd>
              </div>
            )}
            <div>
              <dt className="text-xs text-muted-foreground">Company</dt>
              <dd className="mt-0.5 text-sm">
                {email.company_name ?? "--"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Email</dt>
              <dd className="mt-0.5 text-sm">
                {email.contact_email ?? "--"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Website</dt>
              <dd className="mt-0.5 text-sm">
                {email.company_website ? (
                  <a
                    href={email.company_website}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    {email.company_website.replace(/^https?:\/\//, "")}
                  </a>
                ) : (
                  "--"
                )}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <EmailEditor
        emailId={email.id}
        initialSubject={email.subject}
        initialBody={email.body}
      />

      {email.status === "Pending Review" && (
        <EmailActions emailId={email.id} />
      )}
    </div>
  );
}
