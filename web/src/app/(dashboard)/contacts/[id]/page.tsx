import { notFound } from "next/navigation";
import { getContactById } from "@/lib/queries";
import { ContactDetail } from "@/components/contact-detail";

export default async function ContactDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const contact = await getContactById(id);
  if (!contact) notFound();
  return <ContactDetail contact={contact} backUrl="/contacts" />;
}
