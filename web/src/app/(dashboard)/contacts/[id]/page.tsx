import { notFound } from "next/navigation";
import Link from "next/link";
import { getContactById } from "@/lib/queries";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BodyContent } from "@/components/body-content";

export default async function ContactDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const contact = await getContactById(id);

  if (!contact) notFound();

  const props = [
    {
      label: "Email",
      value: contact.email || "--",
    },
    {
      label: "LinkedIn",
      value: contact.linkedin_url ? (
        <a
          href={contact.linkedin_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          Profile
        </a>
      ) : (
        "--"
      ),
    },
    {
      label: "Company",
      value: contact.company_id ? (
        <Link
          href={`/companies/${contact.company_id}`}
          className="text-primary hover:underline"
        >
          {contact.company_name || "--"}
        </Link>
      ) : (
        "--"
      ),
    },
    {
      label: "Status",
      value: <Badge variant="outline">{contact.status}</Badge>,
    },
    {
      label: "Email Verified",
      value: contact.email_verified ? "Yes" : "No",
    },
  ];

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        href="/contacts"
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        &larr; Contacts
      </Link>

      {/* Heading */}
      <div>
        <h1 className="text-2xl font-semibold text-foreground">
          {contact.name}
        </h1>
        {contact.job_title && (
          <p className="text-sm text-muted-foreground mt-1">
            {contact.job_title}
          </p>
        )}
      </div>

      {/* Properties */}
      <Card>
        <CardHeader>
          <CardTitle>Properties</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3">
            {props.map((p) => (
              <div key={p.label}>
                <dt className="text-xs text-muted-foreground">{p.label}</dt>
                <dd className="text-sm mt-0.5">{p.value}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      {/* Context */}
      {contact.context && (
        <Card>
          <CardHeader>
            <CardTitle>Context</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{contact.context}</p>
          </CardContent>
        </Card>
      )}

      {/* Person Research */}
      <Card>
        <CardHeader>
          <CardTitle>Person Research</CardTitle>
        </CardHeader>
        <CardContent>
          <BodyContent text={contact.body} />
        </CardContent>
      </Card>
    </div>
  );
}
