import { notFound } from "next/navigation";
import { sql } from "@/lib/db";
import { EmailDetail, type EmailData } from "@/components/email-detail";

async function getEmailDetail(id: string): Promise<EmailData | null> {
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
  return (rows[0] as EmailData) ?? null;
}

export default async function CampaignEmailPage({
  params,
}: {
  params: Promise<{ id: string; emailId: string }>;
}) {
  const { id, emailId } = await params;
  const email = await getEmailDetail(emailId);
  if (!email) notFound();
  return (
    <EmailDetail
      email={email}
      backUrl={`/campaigns/${id}/emails`}
      campaignId={id}
    />
  );
}
