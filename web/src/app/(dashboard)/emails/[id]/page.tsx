import { notFound } from "next/navigation";
import { getEmailDetail } from "@/lib/queries";
import { EmailDetail, type EmailData } from "@/components/email-detail";

export default async function EmailDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const email = (await getEmailDetail(id)) as EmailData | null;
  if (!email) notFound();
  return <EmailDetail email={email} backUrl="/emails" />;
}
