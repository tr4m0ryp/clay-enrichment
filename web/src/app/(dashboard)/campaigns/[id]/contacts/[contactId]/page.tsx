import { notFound } from "next/navigation";
import { getContactById } from "@/lib/queries";
import { ContactDetail } from "@/components/contact-detail";

export default async function CampaignContactPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; contactId: string }>;
  searchParams: Promise<{ from?: string }>;
}) {
  const [{ id, contactId }, sp] = await Promise.all([params, searchParams]);
  const contact = await getContactById(contactId);
  if (!contact) notFound();
  const fromLeads = sp.from === "leads";
  return (
    <ContactDetail
      contact={contact}
      backUrl={fromLeads ? `/campaigns/${id}/leads` : `/campaigns/${id}/contacts`}
      backLabel={fromLeads ? "High-Priority Leads" : "Contacts"}
      campaignId={id}
    />
  );
}
