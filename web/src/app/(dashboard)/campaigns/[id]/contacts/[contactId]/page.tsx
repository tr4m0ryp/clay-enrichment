import { notFound } from "next/navigation";
import { getContactById } from "@/lib/queries";
import { ContactDetail } from "@/components/contact-detail";

export default async function CampaignContactPage({
  params,
}: {
  params: Promise<{ id: string; contactId: string }>;
}) {
  const { id, contactId } = await params;
  const contact = await getContactById(contactId);
  if (!contact) notFound();
  return (
    <ContactDetail
      contact={contact}
      backUrl={`/campaigns/${id}/contacts`}
      campaignId={id}
    />
  );
}
