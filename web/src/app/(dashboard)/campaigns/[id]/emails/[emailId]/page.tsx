import { notFound } from "next/navigation";
import { getEmailDetail } from "@/lib/queries";
import { EmailDetail, type EmailData } from "@/components/email-detail";

export default async function CampaignEmailPage({
  params,
}: {
  params: Promise<{ id: string; emailId: string }>;
}) {
  const { id, emailId } = await params;
  const email = (await getEmailDetail(emailId)) as EmailData | null;
  if (!email) notFound();
  return (
    <EmailDetail
      email={email}
      backUrl={`/campaigns/${id}/emails`}
      campaignId={id}
    />
  );
}
