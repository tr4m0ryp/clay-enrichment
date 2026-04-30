import { notFound } from "next/navigation";
import { getContactById } from "@/lib/queries";
import { ContactDetail } from "@/components/contact-detail";

export default async function ContactDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ from?: string }>;
}) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const contact = await getContactById(id);
  if (!contact) notFound();
  const fromLeads = sp.from === "leads";
  return (
    <ContactDetail
      contact={contact}
      backUrl={fromLeads ? "/leads" : "/contacts"}
      backLabel={fromLeads ? "High-Priority Leads" : "Contacts"}
    />
  );
}
